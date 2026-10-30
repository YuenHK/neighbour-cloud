import csv
import io
import sqlite3

import pytest
import test_cloud_database_profile
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deploy.cloud.event_export import EventExportSnapshot
from edge_hub.csv_export import ExportPreparationError, PreparedEventExport
from edge_hub.events import Event, EventStore

prepared = test_cloud_database_profile.prepared


def test_remote_event_store_can_prepare_consistent_csv_without_driver_backup(prepared):
    profile, runtime, _, _, _ = prepared
    path = runtime / 'events.sqlite3'
    snapshots = EventExportSnapshot(path, connection_factory=profile.connect)
    store = EventStore(path, connection_factory=profile.connect, export_snapshot_factory=snapshots)
    try:
        store.add(Event(id='public-synthetic', type='litter_detected', zone='PUBLIC', at_ms=1, severity='notice'))
        export = PreparedEventExport(store)
        try:
            rows = list(csv.reader(io.StringIO(''.join(export))))
        finally:
            export.close()
        assert rows[1][0] == 'public-synthetic'
    finally:
        store.close()


@pytest.fixture
def exporting(prepared, tmp_path):
    profile, runtime, _, _, calls = prepared
    scratch = tmp_path / 'exports'
    scratch.mkdir()
    path, readers = runtime / 'events.sqlite3', []

    def connect(*args, **kwargs):
        assert kwargs['uri'] and args[0].endswith('?mode=ro')
        result = profile.connect(*args, **kwargs)
        readers.append(result)
        return result

    factory = EventExportSnapshot(path, connection_factory=connect, scratch_root=scratch)
    store = EventStore(path, connection_factory=profile.connect, export_snapshot_factory=factory)
    try:
        yield store, factory, readers, scratch, calls
    finally:
        store.close()


def populate(store, count):
    # One synthetic transaction keeps this test about export paging, not fsync.
    with store._connection:
        store._connection.executemany('INSERT INTO events VALUES(?,?,?,?,?,?,?,?)', [
            (f'old-{i}', 'litter_detected', '=PUBLIC-ZONE', 1, 'notice', None, '{}', 'pending')
            for i in range(count)])
        store._connection.executemany('INSERT INTO event_ingest_sequence(event_id) VALUES(?)',
                                      [(f'old-{i}',) for i in range(count)])


def test_all_pages_stable_after_source_change_and_remote_reader_closed_before_header(exporting):
    store, _, readers, scratch, _ = exporting
    populate(store, 503)
    stream = PreparedEventExport(store)
    try:
        assert len(readers) == 1
        with pytest.raises(sqlite3.Error):
            _ = readers[0].in_transaction
        with pytest.raises(sqlite3.Error):
            readers[0].execute('SELECT 1')
        assert len(list(scratch.iterdir())) == 1
        # The dedicated remote snapshot is finished before the client can stall.
        store.update_status('old-502', 'resolved')
        store.clear()
        store.add(Event(id='new', type='litter_detected', zone='PUBLIC', at_ms=2, severity='notice'))
        rows = list(csv.reader(io.StringIO(''.join(stream))))
        assert len(rows) == 504
        assert [row[0] for row in rows[1:]] == [f'old-{i}' for i in range(503)]
        assert all(row[2] == "'=PUBLIC-ZONE" and row[5] == 'pending' for row in rows[1:])
    finally:
        stream.close()
    assert list(scratch.iterdir()) == []
    assert [event.id for event in store.all()] == ['new']
    assert store.export_metrics()['active'] == store.export_metrics()['failed_total'] == 0


def test_snapshot_is_read_only_and_consumer_failure_removes_only_own_copy(exporting):
    store, _, _, scratch, _ = exporting
    (scratch / 'preserve.txt').write_text('preserve')
    with pytest.raises(RuntimeError, match='consumer'), store.export_snapshot() as snapshot:
        with pytest.raises(sqlite3.Error):
            snapshot.execute('DELETE FROM events')
        raise RuntimeError('consumer')
    with pytest.raises(sqlite3.ProgrammingError):
        snapshot.execute('SELECT 1')
    assert [path.name for path in scratch.iterdir()] == ['preserve.txt']
    assert store.export_metrics()['active'] == 0 and store.export_metrics()['failed_total'] == 1


def test_early_close_releases_slot_and_capacity_refusal_has_no_remote_call(exporting):
    store, _, readers, scratch, calls = exporting
    streams = []
    try:
        streams = [PreparedEventExport(store), PreparedEventExport(store)]
        before = len(calls)
        with pytest.raises(ExportPreparationError):
            PreparedEventExport(store)
        assert len(calls) == before and len(readers) == 2
        assert len(list(scratch.iterdir())) == 2
        streams[0].close()
        streams[0].close()
        replacement = PreparedEventExport(store)
        replacement.close()
    finally:
        for stream in streams:
            stream.close()
    assert list(scratch.iterdir()) == []
    metrics = store.export_metrics()
    assert metrics['active'] == metrics['failed_total'] == 0
    assert metrics['prepared_total'] == 3 and metrics['rejected_total'] == 1


@pytest.mark.parametrize('failure', ['connect', 'sql', 'capacity', 'deadline'])
def test_failure_before_header_cleans_temp_and_never_reports_prepared(exporting, failure, monkeypatch):
    from deploy.cloud import event_export

    store, factory, readers, scratch, _ = exporting
    if failure == 'connect':
        monkeypatch.setattr(factory, 'connect', lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError('PRIVATE')))
    elif failure == 'sql':
        monkeypatch.setattr(event_export, 'snapshot', lambda *a, **k: (_ for _ in ()).throw(ValueError('PRIVATE')))
    elif failure == 'capacity':
        monkeypatch.setattr(factory, 'max_bytes', 1024)
    else:
        ticks = iter([0, 0, 6])
        monkeypatch.setattr(factory, 'clock', lambda: next(ticks))
    with pytest.raises(ExportPreparationError) as error:
        PreparedEventExport(store)
    assert 'PRIVATE' not in str(error.value)
    assert list(scratch.iterdir()) == []
    for reader in readers:
        with pytest.raises(sqlite3.Error):
            reader.execute('SELECT 1')
    metrics = store.export_metrics()
    assert metrics['active'] == metrics['prepared_total'] == 0 and metrics['failed_total'] == 1
    assert store.stats()['total'] == 0  # Failure did not damage the source.


def test_missing_cloud_export_provider_fails_as_preparation_error_not_attribute_error(prepared):
    profile, runtime, _, _, _ = prepared
    store = EventStore(runtime / 'events.sqlite3', connection_factory=profile.connect)
    try:
        with pytest.raises(ExportPreparationError):
            PreparedEventExport(store)
        assert store.export_metrics()['active'] == 0
    finally:
        store.close()


def test_real_http_prepares_before_headers_and_can_stream_from_worker_threads(exporting):
    store, _, _, scratch, _ = exporting
    populate(store, 3)
    from starlette.background import BackgroundTask
    from starlette.responses import JSONResponse, StreamingResponse
    app = FastAPI()

    @app.get('/events.csv')
    def export():
        try:
            prepared = PreparedEventExport(store)
        except ExportPreparationError:
            return JSONResponse({'detail': 'event export temporarily unavailable'}, status_code=503)
        return StreamingResponse(prepared, media_type='text/csv',
                                 headers={'Content-Disposition': 'attachment; filename="events.csv"'},
                                 background=BackgroundTask(prepared.close))

    with TestClient(app) as client:
        response = client.get('/events.csv')
        assert response.status_code == 200 and 'attachment' in response.headers['content-disposition']
        assert len(list(csv.reader(io.StringIO(response.text)))) == 4
    assert list(scratch.iterdir()) == [] and store.export_metrics()['active'] == 0


def test_invalid_explicit_provider_is_rejected_before_opening_database(tmp_path):
    path = tmp_path / 'should-not-exist.sqlite3'
    with pytest.raises(ValueError):
        EventStore(path, export_snapshot_factory=object())
    assert not path.exists()
    for options in ({'timeout': 6}, {'timeout': float('nan')}, {'timeout': True},
                    {'max_bytes': 129 * 1024 * 1024}, {'max_bytes': 1.5},
                    {'scratch_root': tmp_path / 'absent'}):
        with pytest.raises(ValueError):
            EventExportSnapshot(path, connection_factory=sqlite3.connect, **options)
