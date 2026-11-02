import importlib

import pytest
from fastapi.testclient import TestClient

from edge_hub.events import EventStore


@pytest.mark.parametrize('provided,configured,matches', [
    ('same-key', 'same-key', True), (None, 'same-key', False), ('', '', False),
    ('prefix', 'prefix-longer', False), ('KEY', 'key', False), ('key ', 'key', False),
    (' key', 'key', False), ('私密', '私密', False),
])
def test_event_keys_are_nonempty_ascii_exact_matches(provided, configured, matches):
    hub = importlib.import_module('edge_hub.app')
    assert hub.ascii_key_matches(provided, configured) is matches


@pytest.fixture
def isolated_api(monkeypatch):
    hub = importlib.import_module('edge_hub.app')
    store = EventStore()
    monkeypatch.setattr(hub, 'store', store)
    monkeypatch.setattr(hub, 'OPERATOR_KEY', 'encoding-operator')
    monkeypatch.setattr(hub, 'EVENT_INGEST_KEY', 'encoding-collector')
    try:
        yield TestClient(hub.app, raise_server_exceptions=False), store, hub
    finally:
        store.close()


def event():
    return {'id': 'encoding-test', 'type': 'robot_fault', 'zone': 'test',
            'at_ms': 0, 'severity': 'notice'}


@pytest.mark.parametrize('header', [b'X-Operator-Key', b'X-Event-Ingest-Key'])
def test_non_ascii_event_key_is_denied_without_server_error(isolated_api, header):
    client, store, _ = isolated_api
    response = client.post('/api/v1/events', json=event(), headers=[(header, b'private-\xff')])
    assert response.status_code == 403
    assert 'private' not in response.text
    assert store.latest_cursor() == 0 and store.all() == []


@pytest.mark.parametrize('good,bad', [
    ((b'X-Operator-Key', b'encoding-operator'), (b'X-Event-Ingest-Key', b'\xff')),
    ((b'X-Event-Ingest-Key', b'encoding-collector'), (b'X-Operator-Key', b'\xff')),
])
def test_valid_independent_writer_key_survives_bad_other_header(isolated_api, good, bad):
    client, store, _ = isolated_api
    response = client.post('/api/v1/events', json=event(), headers=[good, bad])
    assert response.status_code == 201 and store.latest_cursor() == 1
    assert client.post('/api/v1/robot/lease', headers=[
        (b'X-Event-Ingest-Key', b'encoding-collector')]).status_code == 403


@pytest.mark.parametrize('configuration', ['OPERATOR_KEY', 'EVENT_INGEST_KEY'])
def test_non_ascii_configured_event_key_fails_closed(isolated_api, monkeypatch, configuration):
    client, store, hub = isolated_api
    monkeypatch.setattr(hub, configuration, '私密設定')
    response = client.post('/api/v1/events', json=event(), headers={
        'X-Operator-Key': 'incorrect', 'X-Event-Ingest-Key': 'incorrect'})
    assert response.status_code == 403 and store.latest_cursor() == 0
    assert '私密' not in response.text
