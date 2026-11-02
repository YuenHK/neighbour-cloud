import csv
import io
import sqlite3

import pytest

from edge_hub.csv_export import export_event_rows
from edge_hub.events import Event, EventStore


def add(store, identity):
    store.add(Event(id=identity, type='litter_detected', zone='A1', at_ms=10, severity='notice'))


@pytest.mark.parametrize('file_backed', [False, True])
def test_export_preserves_all_pages_after_source_review_clear_and_new_insert(tmp_path, file_backed):
    store = EventStore(tmp_path / 'source.sqlite3' if file_backed else ':memory:')
    try:
        for index in range(502):
            add(store, f'old-{index}')
        stream = export_event_rows(store)
        text = next(stream)
        store.update_status('old-501', 'resolved')
        store.clear()
        add(store, 'new')
        text += ''.join(stream)
        rows = list(csv.reader(io.StringIO(text)))
        assert len(rows) == 503
        assert [row[0] for row in rows[1:]] == [f'old-{index}' for index in range(502)]
        assert all(row[5] == 'pending' for row in rows[1:])
        assert [event.id for event in store.all()] == ['new']
    finally:
        store.close()


def test_generator_close_closes_and_removes_only_temporary_snapshot(tmp_path, monkeypatch):
    import edge_hub.events as module

    original = module.tempfile.TemporaryDirectory
    monkeypatch.setattr(module.tempfile, 'TemporaryDirectory',
                        lambda **kwargs: original(dir=tmp_path, **kwargs))
    store = EventStore()
    try:
        add(store, 'old')
        stream = export_event_rows(store)
        next(stream)
        assert len(list(tmp_path.iterdir())) == 1
        stream.close()
        assert list(tmp_path.iterdir()) == []
        add(store, 'still-writable')
        assert store.stats()['total'] == 2
    finally:
        store.close()


def test_snapshot_failure_releases_lock_and_cleans_temporary_files(tmp_path, monkeypatch):
    import edge_hub.events as module

    original = module.tempfile.TemporaryDirectory
    monkeypatch.setattr(module.tempfile, 'TemporaryDirectory',
                        lambda **kwargs: original(dir=tmp_path, **kwargs))
    store = EventStore()
    try:
        add(store, 'old')
        with pytest.raises(RuntimeError, match='consumer failed'), store.export_snapshot() as snapshot:
            assert snapshot.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
            raise RuntimeError('consumer failed')
        with pytest.raises(sqlite3.ProgrammingError):
            snapshot.execute('SELECT 1')
        assert list(tmp_path.iterdir()) == []
        add(store, 'still-writable')
    finally:
        store.close()


def test_backup_budget_failure_cleans_snapshot_and_releases_source_lock(tmp_path, monkeypatch):
    import edge_hub.events as module

    original = module.tempfile.TemporaryDirectory
    monkeypatch.setattr(module.tempfile, 'TemporaryDirectory',
                        lambda **kwargs: original(dir=tmp_path, **kwargs))
    times = iter([0, 6])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(times))
    store = EventStore()
    try:
        add(store, 'old')
        stream = export_event_rows(store)
        with pytest.raises(TimeoutError, match='snapshot budget'):
            next(stream)
        assert list(tmp_path.iterdir()) == []
        assert store._lock.acquire(blocking=False)
        store._lock.release()
        assert store.stats()['total'] == 1
    finally:
        store.close()


def test_empty_export_has_only_header_and_keeps_source_empty():
    store = EventStore()
    try:
        rows = list(csv.reader(io.StringIO(''.join(export_event_rows(store)))))
        assert rows == [['id', 'type', 'zone', 'at_ms', 'severity', 'status', 'evidence']]
        assert store.stats()['total'] == 0
    finally:
        store.close()
