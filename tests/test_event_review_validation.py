import importlib
import json

import pytest
from fastapi.testclient import TestClient

from edge_hub.events import Event, EventStore


@pytest.fixture
def isolated_api(monkeypatch):
    hub = importlib.import_module('edge_hub.app')
    store = EventStore()
    store.add(Event(id='private-event-id', type='robot_fault', zone='test', at_ms=1,
                    severity='notice'))
    monkeypatch.setattr(hub, 'store', store)
    monkeypatch.setattr(hub, 'OPERATOR_KEY', 'review-validation-fixture')
    try:
        yield TestClient(hub.app, raise_server_exceptions=False), store
    finally:
        store.close()


@pytest.mark.parametrize('raw', [
    json.dumps({'status': '\ud800'}, ensure_ascii=True),
    json.dumps({'status': 'private-invalid-status' * 100}),
    json.dumps({'private-field': 'private-value'}),
    '{"status":"private-malformed",}',
], ids=['unpaired-surrogate', 'private-enum', 'missing-status', 'malformed-json'])
def test_review_validation_is_fixed_redacted_422_without_sql_or_mutation(isolated_api, raw):
    client, store = isolated_api
    statements = []
    store._connection.set_trace_callback(statements.append)
    response = client.patch('/api/v1/events/private-event-id', content=raw,
        headers={'Content-Type': 'application/json', 'X-Operator-Key': 'review-validation-fixture'})
    assert response.status_code == 422
    assert response.json() == {'detail': 'event payload failed validation'}
    assert response.headers['cache-control'] == 'no-store'
    assert 'private-' not in response.text and statements == []
    assert store.query()[0].status == 'pending' and store.latest_cursor() == 1


def test_valid_review_and_other_route_validation_contract_remain_unchanged(isolated_api):
    client, store = isolated_api
    response = client.patch('/api/v1/events/private-event-id', json={'status': 'resolved'},
                            headers={'X-Operator-Key': 'review-validation-fixture'})
    assert response.status_code == 200 and store.query()[0].status == 'resolved'
    # Robot validation is now separately redacted; an ordinary query still uses
    # the default structured validation contract.
    other = client.get('/api/v1/events', params={'limit': 'not-an-integer'})
    assert other.status_code == 422 and isinstance(other.json()['detail'], list)
    assert client.patch('/api/v1/not-a-route', json={}).status_code == 404
