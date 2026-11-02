import importlib
import time

import pytest
from fastapi.testclient import TestClient

from edge_hub.robot_control import RobotController


@pytest.fixture
def client(monkeypatch):
    module = importlib.import_module('edge_hub.app')
    controller = RobotController()
    monkeypatch.setattr(module, 'robot_control', controller)
    monkeypatch.setattr(module, 'OPERATOR_KEY', 'test-operator-private-key')
    yield TestClient(module.app)
    controller.close()


AUTH = {'X-Operator-Key': 'test-operator-private-key'}


def test_audit_history_pagination_keeps_auth_and_list_contract(client):
    for _ in range(5):
        assert client.post('/api/v1/robot/software-stop', headers=AUTH).status_code == 200
    assert client.get('/api/v1/robot/audit?before_id=4').status_code == 403
    assert client.get('/api/v1/robot/audit?before_id=4',
                      headers={'X-Operator-Key': 'collector-only'}).status_code == 403
    first = client.get('/api/v1/robot/audit?limit=2', headers=AUTH).json()
    assert [row['id'] for row in first] == [5, 4]
    client.post('/api/v1/robot/software-stop', headers=AUTH)
    second = client.get('/api/v1/robot/audit?limit=2&before_id=4', headers=AUTH).json()
    assert [row['id'] for row in second] == [3, 2]
    assert client.get('/api/v1/robot/audit?before_id=1', headers=AUTH).json() == []
    for query in ('limit=0', 'limit=201', 'before_id=0', 'before_id=-1',
                  'before_id=9223372036854775808', 'before_id=oops'):
        assert client.get('/api/v1/robot/audit?' + query, headers=AUTH).status_code == 422


def test_robot_api_requires_auth_and_rejects_cross_origin(client):
    assert client.post('/api/v1/robot/lease').status_code == 403
    assert client.post('/api/v1/robot/lease', headers={**AUTH, 'Origin': 'https://attacker.example'}).status_code == 403
    result = client.get('/api/v1/robot/status').json()
    assert result['mode'] == 'simulation' and not result['connected']
    assert result['hardware_watchdog_verified'] is False


def test_closed_audit_returns_service_unavailable(client):
    importlib.import_module('edge_hub.app').robot_control.close()
    response = client.get('/api/v1/robot/audit?before_id=2', headers=AUTH)
    assert response.status_code == 503
    assert 'control_backend_closed' in response.text


def test_default_operator_key_cannot_control_even_simulation(client, monkeypatch):
    monkeypatch.setattr('edge_hub.app.OPERATOR_KEY', 'local-operator')
    assert client.post('/api/v1/robot/lease', headers={'X-Operator-Key': 'local-operator'}).status_code == 503


def test_lease_command_release_stop_and_audit_end_to_end(client):
    lease = client.post('/api/v1/robot/lease', headers=AUTH).json()
    command = {'lease_token': lease['lease_token'], 'seq': 0, 'issued_at_ms': int(time.time() * 1000),
               'ttl_ms': 500, 'direction': 'forward'}
    response = client.post('/api/v1/robot/command', headers=AUTH, json=command)
    assert response.status_code == 200 and response.json()['direction'] == 'forward'
    response = client.post('/api/v1/robot/software-stop', headers=AUTH)
    assert response.json()['software_stop_latched']
    assert client.post('/api/v1/robot/lease', headers=AUTH).status_code == 423
    assert client.post('/api/v1/robot/reset-software-stop', headers=AUTH,
                       json={'confirmed_stationary': False}).status_code == 422
    assert client.post('/api/v1/robot/reset-software-stop', headers=AUTH,
                       json={'confirmed_stationary': True}).json()['direction'] == 'stop'
    assert client.get('/api/v1/robot/audit').status_code == 403
    audit = client.get('/api/v1/robot/audit', headers=AUTH).json()
    assert any(row['action'] == 'forward' for row in audit)
    assert lease['lease_token'] not in str(audit)
