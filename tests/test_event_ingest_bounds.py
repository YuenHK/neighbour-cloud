import importlib
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from edge_hub.event_ingest import IngestEvent
from edge_hub.events import Event, EventStore


def payload(**changes):
    return {'id': 'fixture', 'type': 'litter_detected', 'zone': 'A1', 'at_ms': 1,
            'severity': 'notice', **changes}


@pytest.fixture
def isolated_api(monkeypatch):
    hub = importlib.import_module('edge_hub.app')
    store = EventStore()
    monkeypatch.setattr(hub, 'store', store)
    monkeypatch.setattr(hub, 'OPERATOR_KEY', 'unit-test-operator')
    monkeypatch.setattr(hub, 'EVENT_INGEST_KEY', 'unit-test-collector')
    try:
        yield TestClient(hub.app), store
    finally:
        store.close()


@pytest.mark.parametrize('status', ['confirmed', 'false_positive', 'resolved'])
def test_collector_cannot_pre_review_new_event(isolated_api, status):
    client, store = isolated_api
    response = client.post('/api/v1/events', json=payload(status=status),
                           headers={'X-Event-Ingest-Key': 'unit-test-collector'})
    assert response.status_code == 422 and store.latest_cursor() == 0
    assert store.all() == []


@pytest.mark.parametrize('timestamp', [True, -1, 2**63, '1', 1.5])
def test_unsafe_timestamp_rejected_before_sqlite(isolated_api, timestamp):
    client, store = isolated_api
    response = client.post('/api/v1/events', json=payload(at_ms=timestamp),
                           headers={'X-Event-Ingest-Key': 'unit-test-collector'})
    assert response.status_code == 422 and store.latest_cursor() == 0


@pytest.mark.parametrize('changes', [{'id': ''}, {'id': 'x' * 129}, {'zone': 'x' * 129},
                                    {'details': {'text': '繁體' * 3000}}, {'unexpected': True}])
def test_bounded_fields_and_unknown_properties(isolated_api, changes):
    client, store = isolated_api
    assert client.post('/api/v1/events', json=payload(**changes),
                       headers={'X-Operator-Key': 'unit-test-operator'}).status_code == 422
    assert store.all() == []


def test_pending_creation_operator_review_and_legacy_reads_remain_compatible(isolated_api):
    client, store = isolated_api
    created = client.post('/api/v1/events', json=payload(status='pending', at_ms=0),
                          headers={'X-Event-Ingest-Key': 'unit-test-collector'})
    assert created.status_code == 201 and created.json()['status'] == 'pending'
    assert client.patch('/api/v1/events/fixture', json={'status': 'resolved'},
                        headers={'X-Operator-Key': 'unit-test-operator'}).status_code == 200
    store.add(Event(**payload(id='legacy', zone='x' * 129, status='confirmed')))
    response = client.get('/api/v1/events')
    assert response.status_code == 200
    assert {row['id']: row['status'] for row in response.json()} == {
        'fixture': 'resolved', 'legacy': 'confirmed'}


def test_details_utf8_exact_limit_and_nonfinite_values():
    details = {'text': 'x' * (16384 - len(json.dumps({'text': ''}, separators=(',', ':'))))}
    assert IngestEvent(**payload(details=details)).details == details
    details['text'] += 'x'
    with pytest.raises(ValidationError):
        IngestEvent(**payload(details=details))
    with pytest.raises(ValidationError):
        IngestEvent(**payload(details={'number': float('nan')}))
