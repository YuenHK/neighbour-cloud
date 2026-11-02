import importlib
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from edge_hub.csv_export import ExportPreparationError, PreparedEventExport
from edge_hub.events import EventStore


@pytest.mark.parametrize('error_type', [OSError, TimeoutError, sqlite3.OperationalError])
def test_failed_preparation_returns_fixed_503_before_csv_headers(monkeypatch, error_type):
    module = importlib.import_module('edge_hub.app')
    class BrokenStore:
        @contextmanager
        def export_snapshot(self):
            raise error_type('PRIVATE_PATH_AND_DETAILS')
            yield  # pragma: no cover
    monkeypatch.setattr(module, 'store', BrokenStore())
    response = TestClient(module.app, raise_server_exceptions=False).get('/api/v1/events.csv')
    assert response.status_code == 503
    assert response.json() == {'detail': 'event export temporarily unavailable'}
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert 'content-disposition' not in response.headers
    assert 'PRIVATE_PATH_AND_DETAILS' not in response.text


def test_prepared_export_close_before_body_consumption_removes_snapshot(tmp_path, monkeypatch):
    import edge_hub.events as module

    original = module.tempfile.TemporaryDirectory
    monkeypatch.setattr(module.tempfile, 'TemporaryDirectory',
                        lambda **kwargs: original(dir=tmp_path, **kwargs))
    store = EventStore()
    try:
        prepared = PreparedEventExport(store)
        assert len(list(tmp_path.iterdir())) == 1
        prepared.close()
        prepared.close()
        assert list(tmp_path.iterdir()) == []
        assert list(prepared) == []
    finally:
        store.close()


def test_successful_http_export_preserves_download_headers_and_cleans_snapshot(tmp_path, monkeypatch):
    from edge_hub import events

    module = importlib.import_module('edge_hub.app')
    original = events.tempfile.TemporaryDirectory
    monkeypatch.setattr(events.tempfile, 'TemporaryDirectory',
                        lambda **kwargs: original(dir=tmp_path, **kwargs))
    store = EventStore()
    monkeypatch.setattr(module, 'store', store)
    try:
        response = TestClient(module.app).get('/api/v1/events.csv')
        assert response.status_code == 200
        assert response.headers['content-disposition'] == 'attachment; filename="events.csv"'
        assert response.headers['cache-control'] == 'no-store'
        assert response.text.startswith('"id","type","zone"')
        assert list(tmp_path.iterdir()) == []
    finally:
        store.close()


def test_preparation_error_has_no_private_exception_chain(monkeypatch):
    import traceback

    import edge_hub.csv_export as module

    def broken(store):
        raise sqlite3.OperationalError('PRIVATE_PATH_AND_DETAILS')
        yield  # pragma: no cover
    monkeypatch.setattr(module, 'export_event_rows', broken)
    with pytest.raises(ExportPreparationError) as error:
        PreparedEventExport(None)
    assert 'PRIVATE_PATH_AND_DETAILS' not in ''.join(traceback.format_exception(error.value))


def test_response_background_closes_prepared_snapshot_even_before_body_is_consumed(tmp_path, monkeypatch):
    import asyncio

    from edge_hub import events

    module = importlib.import_module('edge_hub.app')
    original = events.tempfile.TemporaryDirectory
    monkeypatch.setattr(events.tempfile, 'TemporaryDirectory',
                        lambda **kwargs: original(dir=tmp_path, **kwargs))
    store = EventStore()
    monkeypatch.setattr(module, 'store', store)
    try:
        response = module.export_events_csv()
        assert len(list(tmp_path.iterdir())) == 1
        asyncio.run(response.background())
        assert list(tmp_path.iterdir()) == []
    finally:
        store.close()
