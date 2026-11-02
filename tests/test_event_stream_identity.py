import importlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from edge_hub.events import Event, EventStore, EventStreamMismatch
from tools.backup_events import backup


def test_identity_is_persistent_across_reopen_clear_and_backup_but_new_db_differs(tmp_path):
    path, copy = tmp_path / 'stream.sqlite3', tmp_path / 'copy.sqlite3'
    store = EventStore(path)
    initial = store.stream_state()
    assert len(initial['stream_id']) == 32 and initial['cursor'] == 0
    store.add(Event(id='one', type='temperature_drill', zone='test', at_ms=1, severity='notice'))
    store.clear()
    state = store.stream_state()
    assert state == {**initial, 'cursor': 1}
    store.close()
    backup(path, copy)
    for target in (path, copy):
        reopened = EventStore(target)
        try:
            assert reopened.stream_state() == state
            assert reopened.page(after=1, expected_stream_id=state['stream_id'])['items'] == []
        finally:
            reopened.close()
    other = EventStore()
    try:
        assert other.stream_state()['stream_id'] != state['stream_id']
        with pytest.raises(EventStreamMismatch):
            other.page(expected_stream_id=state['stream_id'])
    finally:
        other.close()


def test_corrupt_persisted_identity_is_rejected_not_regenerated(tmp_path):
    path = tmp_path / 'broken.sqlite3'
    store = EventStore(path)
    store.close()
    with sqlite3.connect(path) as database:
        database.execute("UPDATE event_stream_metadata SET stream_id='not-a-valid-id'")
    with pytest.raises(ValueError, match='do not regenerate'):
        EventStore(path)
    with sqlite3.connect(path) as database:
        assert database.execute('SELECT stream_id FROM event_stream_metadata').fetchone()[0] == 'not-a-valid-id'


def test_stream_api_and_bound_pages_reject_wrong_stream_or_cursor_without_fallback(monkeypatch):
    module = importlib.import_module('edge_hub.app')
    store = EventStore()
    monkeypatch.setattr(module, 'store', store)
    try:
        client = TestClient(module.app)
        response = client.get('/api/v1/events/stream')
        state = response.json()
        assert response.headers['cache-control'] == 'no-store'
        assert state == store.stream_state()
        identity = state['stream_id']
        good = client.get('/api/v1/events/page', params={'stream_id': identity}).json()
        assert good['stream_id'] == identity and good['items'] == []
        assert client.get('/api/v1/events/page', params={'stream_id': identity, 'after': 1}).status_code == 409
        wrong = '1' * 32 if identity != '1' * 32 else '2' * 32
        assert client.get('/api/v1/events/page', params={'stream_id': wrong}).status_code == 409
        assert client.get('/api/v1/events/page', params={'stream_id': 'invalid'}).status_code == 422
        assert client.get('/api/v1/events/cursor').json() == {'cursor': 0}
        assert 'stream_id' not in client.get('/api/v1/events/page').json()
    finally:
        store.close()
