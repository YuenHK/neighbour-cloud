import csv
import importlib
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient

from edge_hub.csv_export import export_event_rows, safe_csv_cell
from edge_hub.events import Event, EventStore


def event(identity, at_ms=10, zone='A1'):
    return Event(id=identity, type='litter_detected', at_ms=at_ms, zone=zone, severity='notice')


def test_ingestion_pages_do_not_lose_equal_or_late_timestamps():
    store = EventStore()
    try:
        for identity, timestamp in [('one', 1000), ('late', 1), ('same', 1000)]:
            store.add(event(identity, timestamp))
        first = store.page(limit=2)
        second = store.page(after=first['next_cursor'], limit=2)
        assert [item.id for item in first['items'] + second['items']] == ['one', 'late', 'same']
        assert first['has_more'] and not second['has_more']
        assert second['next_cursor'] == store.latest_cursor()
    finally:
        store.close()


def test_clear_does_not_reuse_sequence_and_duplicate_insert_rolls_back():
    store = EventStore()
    try:
        store.add(event('one'))
        cursor = store.latest_cursor()
        with pytest.raises(sqlite3.IntegrityError):
            store.add(event('one'))
        store.clear()
        store.add(event('new'))
        assert store.latest_cursor() > cursor
        assert [x.id for x in store.page(after=cursor)['items']] == ['new']
    finally:
        store.close()


def test_old_database_is_migrated_without_deleting_events(tmp_path):
    path = tmp_path / 'old.sqlite3'
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE events(id TEXT PRIMARY KEY,type TEXT,zone TEXT,at_ms INTEGER,'
                       'severity TEXT,evidence TEXT,details_json TEXT,status TEXT)')
    connection.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?)',
                       ('old', 'litter_detected', 'A1', 1, 'notice', None, '{}', 'pending'))
    connection.commit()
    connection.close()
    store = EventStore(path)
    assert [item.id for item in store.page()['items']] == ['old']
    store.close()


def test_cursor_never_rewinds_when_events_are_empty_or_reopened(tmp_path):
    path = tmp_path / 'events.sqlite3'
    store = EventStore(path)
    store.add(event('first'))
    cursor = store.latest_cursor()
    store.clear()
    assert store.latest_cursor() == cursor
    assert store.page(after=cursor) == {'items': [], 'next_cursor': cursor, 'has_more': False}
    store.close()
    store = EventStore(path)
    try:
        assert store.latest_cursor() == cursor
        store.add(event('after-restart'))
        assert store.latest_cursor() > cursor
        assert [row.id for row in store.page(after=cursor)['items']] == ['after-restart']
    finally:
        store.close()


def test_reopening_populated_store_does_not_consume_unused_sequence_numbers(tmp_path):
    path = tmp_path / 'events.sqlite3'
    store = EventStore(path)
    for identity in ('one', 'two', 'three'):
        store.add(event(identity))
    cursor = store.latest_cursor()
    store.close()
    for _ in range(3):
        store = EventStore(path)
        store.close()
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT seq FROM sqlite_sequence WHERE name='event_ingest_sequence'").fetchone()[0] == cursor


def test_backup_restore_keeps_deleted_high_water_and_review_status(tmp_path):
    from tools.backup_events import backup

    source, copy = tmp_path / 'original.sqlite3', tmp_path / 'restored.sqlite3'
    store = EventStore(source)
    store.add(event('deleted'))
    old_cursor = store.latest_cursor()
    store.clear()
    backup(source, copy)
    restored = EventStore(copy)
    try:
        assert restored.latest_cursor() == old_cursor
        restored.add(event('probe'))
        restored.update_status('probe', 'confirmed')
        assert restored.page(after=old_cursor)['items'][0].status == 'confirmed'
        assert store.stats()['total'] == 0
        assert store.latest_cursor() == old_cursor
    finally:
        restored.close()
        store.close()


@pytest.mark.parametrize('value', ['=1+1', '+SUM(A1)', '-1+2', '@SUM(A1)', '\t=1',
                                   '\r=1', '\n=1', '  =1', '\ufeff=1', '＝1+1', '＋1', '－1', '＠1',
                                   '\v=1', '\f=1', '\u00a0=1'])
def test_spreadsheet_formula_and_control_prefixes_are_neutralized(value):
    assert safe_csv_cell(value).startswith("'")


def test_csv_quotes_separators_and_uses_a_bounded_snapshot_without_mutating_db():
    store = EventStore()
    try:
        zone = '=HYPERLINK("https://example.invalid","x"),\n=1'
        store.add(event('old', zone=zone))
        output = export_event_rows(store)
        header = next(output)
        store.add(event('new-after-snapshot'))
        text = header + ''.join(output)
        rows = list(csv.reader(io.StringIO(text)))
        assert len(rows) == 2 and all(len(row) == 7 for row in rows)
        assert rows[1][2] == "'" + zone
        assert 'new-after-snapshot' not in text
        assert next(x for x in store.all() if x.id == 'old').zone == zone
    finally:
        store.close()


@pytest.fixture
def api(monkeypatch):
    module = importlib.import_module('edge_hub.app')
    store = EventStore()
    monkeypatch.setattr(module, 'store', store)
    monkeypatch.setattr(module, 'EVENT_INGEST_KEY', 'collector-only-secret')
    yield TestClient(module.app), module
    store.close()


def test_event_writes_require_scoped_credentials_and_collector_cannot_control_robot(api):
    client, module = api
    payload = event('writer').model_dump()
    assert client.post('/api/v1/events', json=payload).status_code == 403
    headers = {'X-Event-Ingest-Key': 'collector-only-secret'}
    assert client.post('/api/v1/events', json=payload, headers=headers).status_code == 201
    assert client.post('/api/v1/robot/lease', headers=headers).status_code == 403
    assert client.patch('/api/v1/events/writer', json={'status': 'resolved'}, headers=headers).status_code == 403
    assert client.post('/api/v1/events', json=event('bad-origin').model_dump(), headers={
        'X-Operator-Key': module.OPERATOR_KEY, 'Origin': 'https://untrusted.example'}).status_code == 403


def test_bounded_legacy_list_cursor_pages_and_no_default_writer_key(api, monkeypatch):
    client, module = api
    for index in range(4):
        module.store.add(event(str(index), at_ms=index))
    assert len(client.get('/api/v1/events?limit=2').json()) == 2
    page = client.get('/api/v1/events/page?limit=2').json()
    assert page['has_more'] and len(page['items']) == 2
    assert client.get('/api/v1/events/page?limit=501').status_code == 422
    assert client.get('/api/v1/events?limit=1001').status_code == 422
    assert client.get('/api/v1/events/page?after=' + '9' * 80).status_code == 422
    assert client.get('/api/v1/events/cursor').json()['cursor'] == module.store.latest_cursor()
    monkeypatch.setattr(module, 'OPERATOR_KEY', 'local-operator')
    assert client.post('/api/v1/events', json=event('default-key').model_dump(),
                       headers={'X-Operator-Key': 'local-operator'}).status_code == 403
