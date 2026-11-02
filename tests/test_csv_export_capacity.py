import importlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from edge_hub.csv_export import ExportPreparationError, PreparedEventExport
from edge_hub.events import Event, EventExportBusy, EventStore


def test_capacity_refuses_before_new_temp_and_http_returns_503(tmp_path, monkeypatch):
    from edge_hub import events

    original = events.tempfile.TemporaryDirectory
    monkeypatch.setattr(events.tempfile, 'TemporaryDirectory',
                        lambda **kwargs: original(dir=tmp_path, **kwargs))
    module = importlib.import_module('edge_hub.app')
    store = EventStore()
    monkeypatch.setattr(module, 'store', store)
    streams = []
    try:
        streams = [PreparedEventExport(store), PreparedEventExport(store)]
        assert len(list(tmp_path.iterdir())) == 2
        response = TestClient(module.app).get('/api/v1/events.csv')
        assert response.status_code == 503
        assert response.json() == {'detail': 'event export temporarily unavailable'}
        assert response.headers['cache-control'] == 'no-store'
        assert 'content-disposition' not in response.headers
        assert len(list(tmp_path.iterdir())) == 2
        streams[0].close()
        streams[0].close()
        replacement = PreparedEventExport(store)
        replacement.close()
    finally:
        for stream in streams:
            stream.close()
        store.close()
    assert list(tmp_path.iterdir()) == []


def test_temp_creation_failure_does_not_lose_capacity(monkeypatch):
    from edge_hub import events

    original = events.tempfile.TemporaryDirectory
    calls = 0
    def temporary(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError('injected disk error')
        return original(**kwargs)
    monkeypatch.setattr(events.tempfile, 'TemporaryDirectory', temporary)
    store = EventStore()
    streams = []
    try:
        with pytest.raises(ExportPreparationError):
            PreparedEventExport(store)
        streams = [PreparedEventExport(store), PreparedEventExport(store)]
        with pytest.raises(ExportPreparationError):
            PreparedEventExport(store)
        assert calls == 3
    finally:
        for stream in streams:
            stream.close()
        store.close()


def test_two_worker_snapshots_reject_third_without_blocking_event_writes():
    store = EventStore()
    ready = [threading.Event(), threading.Event()]
    release = threading.Event()
    def worker(index):
        with store.export_snapshot():
            ready[index].set()
            assert release.wait(10)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, index) for index in range(2)]
            try:
                assert all(signal.wait(5) for signal in ready)
                with pytest.raises(EventExportBusy), store.export_snapshot():
                    pytest.fail('capacity must reject entry')
                store.add(Event(id='write-while-streams-open', type='litter_detected',
                                zone='A1', at_ms=10, severity='notice'))
                assert store.stats()['total'] == 1
            finally:
                release.set()
            for future in futures:
                future.result(timeout=5)
        with store.export_snapshot() as snapshot:
            assert snapshot.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
    finally:
        release.set()
        store.close()
