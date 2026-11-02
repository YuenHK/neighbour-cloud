import importlib
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from edge_hub.event_ingest import IngestEvent
from edge_hub.events import EventStore


def payload(**changes):
    return {'id': 'unicode', 'type': 'robot_fault', 'zone': '測試', 'at_ms': 0,
            'severity': 'notice', **changes}


@pytest.mark.parametrize('changes', [
    {'id': '\ud800'}, {'zone': '\udfff'}, {'evidence': 'events/\ud800-blurred.jpg'},
    {'details': {'private': ['\ud800']}}, {'details': {'\ud800': 'private'}},
])
def test_unpaired_surrogates_are_rejected_and_errors_redacted(monkeypatch, changes):
    with pytest.raises(ValidationError):
        IngestEvent(**payload(**changes))
    hub = importlib.import_module('edge_hub.app')
    store = EventStore()
    monkeypatch.setattr(hub, 'store', store)
    monkeypatch.setattr(hub, 'EVENT_INGEST_KEY', 'unicode-test')
    try:
        client = TestClient(hub.app, raise_server_exceptions=False)
        for path in ['/api/v1/events', '/api/v1/events/']:
            response = client.post(path, content=json.dumps(payload(**changes), ensure_ascii=True),
                                  headers={'Content-Type': 'application/json',
                                           'X-Event-Ingest-Key': 'unicode-test'})
            assert response.status_code == 422
            assert response.json() == {'detail': 'event payload failed validation'}
            assert response.headers['cache-control'] == 'no-store'
        assert store.latest_cursor() == 0 and store.all() == []
    finally:
        store.close()


def test_valid_escaped_emoji_and_other_route_validation_unchanged(monkeypatch):
    hub = importlib.import_module('edge_hub.app')
    store = EventStore()
    monkeypatch.setattr(hub, 'store', store)
    monkeypatch.setattr(hub, 'EVENT_INGEST_KEY', 'unicode-test')
    try:
        client = TestClient(hub.app, raise_server_exceptions=False)
        data = payload(id='繁體😀', details={'emoji': '😀'})
        response = client.post('/api/v1/events', content=json.dumps(data, ensure_ascii=True),
                               headers={'Content-Type': 'application/json',
                                        'X-Event-Ingest-Key': 'unicode-test'})
        assert response.status_code == 201 and response.json()['id'] == data['id']
        other = client.get('/api/v1/events/page?after=invalid')
        assert other.status_code == 422 and isinstance(other.json()['detail'], list)
        invalid = client.post('/api/v1/events', json=payload(at_ms='private-secret'))
        assert invalid.status_code == 422 and 'private-secret' not in invalid.text
        assert store.latest_cursor() == 1
    finally:
        store.close()
