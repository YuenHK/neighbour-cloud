import importlib
import json

import pytest
from fastapi.testclient import TestClient

from edge_hub.event_request import EventBodyLimitMiddleware, check_event_json_depth
from edge_hub.events import EventStore


def test_json_depth_boundary_counts_objects_and_arrays():
    check_event_json_depth(b'[' * 32 + b'0' + b']' * 32)
    with pytest.raises(ValueError, match='nesting limit'):
        check_event_json_depth(b'[' * 33 + b'0' + b']' * 33)
    with pytest.raises(ValueError, match='nesting limit'):
        check_event_json_depth(b'{"item":' * 33 + b'0' + b'}' * 33)


def test_quoted_braces_escaped_quotes_and_backslashes_are_not_nesting():
    text = '{[' * 1000 + '\\"quoted"\\' + '}]' * 1000 + '繁體'
    raw = json.dumps({'text': text}, ensure_ascii=False).encode('utf-8')
    check_event_json_depth(raw)
    check_event_json_depth(b'\xef\xbb\xbf' + raw)


@pytest.mark.parametrize('raw', [b'\xff', '{"a":1}'.encode('utf-16'), b'{"a":"\x00"}'])
def test_non_utf8_and_raw_nul_are_rejected(raw):
    with pytest.raises(ValueError):
        check_event_json_depth(raw)


@pytest.mark.parametrize('limit', [True, 0, 129])
def test_invalid_depth_configuration_is_not_enabled(limit):
    with pytest.raises(ValueError, match='budget'):
        EventBodyLimitMiddleware(None, max_depth=limit)


def test_api_rejects_deep_json_before_write_but_accepts_boundary_and_keeps_syntax_validation(monkeypatch):
    hub = importlib.import_module('edge_hub.app')
    store = EventStore()
    monkeypatch.setattr(hub, 'store', store)
    monkeypatch.setattr(hub, 'EVENT_INGEST_KEY', 'depth-test-collector')
    headers = {'X-Event-Ingest-Key': 'depth-test-collector', 'Content-Type': 'application/json'}
    payload = {'id': 'nested', 'type': 'robot_fault', 'zone': 'test', 'at_ms': 0, 'severity': 'notice'}
    value = 0
    for _ in range(31):
        value = [value]
    try:
        client = TestClient(hub.app)
        response = client.post('/api/v1/events', json={**payload, 'details': {'nested': value}},
                               headers=headers)
        assert response.status_code == 400 and store.latest_cursor() == 0
        assert response.json() == {'detail': 'event JSON exceeds nesting limit'}
        assert response.headers['cache-control'] == 'no-store'
        assert client.post('/api/v1/events', json={**payload, 'details': {'nested': value[0]}},
                           headers=headers).status_code == 201
        assert client.post('/api/v1/events', content='{"invalid":}', headers=headers).status_code == 422
    finally:
        store.close()
