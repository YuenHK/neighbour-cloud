import importlib

import pytest
from fastapi.testclient import TestClient

from edge_hub.events import Event, EventStore


@pytest.mark.parametrize('method,path,body', [
    ('PATCH', '/api/v1/events/fixture', {'status': 'resolved'}),
    ('DELETE', '/api/v1/events', None),
    ('GET', '/api/v1/diagnostics/metrics', None),
    ('POST', '/api/v1/robot/lease', None),
])
def test_default_key_never_reaches_operator_operation(monkeypatch, method, path, body):
    hub = importlib.import_module('edge_hub.app')
    monkeypatch.setattr(hub, 'OPERATOR_KEY', 'local-operator')
    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError('unauthorized operation reached a dependency')
    monkeypatch.setattr(hub, 'store', Forbidden())
    monkeypatch.setattr(hub, 'robot_control', Forbidden())
    monkeypatch.setattr(hub, 'event_fanout', Forbidden())
    client = TestClient(hub.app, raise_server_exceptions=False)
    response = client.request(method, path, json=body, headers={'X-Operator-Key': 'local-operator'})
    assert response.status_code == 503
    assert client.request(method, path, json=body).status_code == 403


@pytest.mark.parametrize('configured,provided', [('', ''), ('private-\xff', 'private-\xff'),
                                               ('configured-ascii', 'private-\xff')])
def test_empty_or_non_ascii_operator_credentials_fail_closed(monkeypatch, configured, provided):
    hub = importlib.import_module('edge_hub.app')
    monkeypatch.setattr(hub, 'OPERATOR_KEY', configured)
    with pytest.raises(hub.HTTPException) as error:
        hub.require_operator(provided)
    assert error.value.status_code == 403
    assert 'private' not in error.value.detail


def test_configured_operator_can_review_and_clear_but_collector_cannot(monkeypatch, tmp_path):
    hub = importlib.import_module('edge_hub.app')
    store = EventStore()
    store.add(Event(id='fixture', type='robot_fault', zone='test', at_ms=1, severity='notice'))
    monkeypatch.setattr(hub, 'store', store)
    monkeypatch.setattr(hub, 'EVENT_DATA_ROOT', tmp_path)
    monkeypatch.setattr(hub, 'OPERATOR_KEY', 'operator-policy-fixture')
    monkeypatch.setattr(hub, 'EVENT_INGEST_KEY', 'collector-policy-fixture')
    try:
        client = TestClient(hub.app, raise_server_exceptions=False)
        collector = {'X-Event-Ingest-Key': 'collector-policy-fixture'}
        assert client.patch('/api/v1/events/fixture', json={'status': 'resolved'},
                            headers=collector).status_code == 403
        assert client.delete('/api/v1/events', headers=collector).status_code == 403
        assert store.all()[0].status == 'pending'
        operator = {'X-Operator-Key': 'operator-policy-fixture'}
        assert client.patch('/api/v1/events/fixture', json={'status': 'resolved'},
                            headers=operator).status_code == 200
        assert client.delete('/api/v1/events', headers=operator).json() == {
            'deleted': 1, 'deleted_evidence': 0}
    finally:
        store.close()
