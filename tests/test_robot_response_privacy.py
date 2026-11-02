"""Only disposable simulation HTTP requests; no SDK, service restart or device."""
import importlib
import json

import pytest
from fastapi.testclient import TestClient

from edge_hub.robot_control import RobotController

AUTH = {'X-Operator-Key': 'private-test-operator'}
SECRET = 'private-submitted-lease-token'


@pytest.fixture
def client(monkeypatch):
    module = importlib.import_module('edge_hub.app')
    controller = RobotController()
    monkeypatch.setattr(module, 'robot_control', controller)
    monkeypatch.setattr(module, 'OPERATOR_KEY', AUTH['X-Operator-Key'])
    yield TestClient(module.app)
    controller.close()


@pytest.mark.parametrize('path,payload', [
    ('command', {'lease_token': SECRET, 'seq': -1, 'issued_at_ms': 1, 'ttl_ms': 500, 'direction': 'stop'}),
    ('command', {'lease_token': SECRET, 'extra_private': SECRET}),
    ('simulation/command', {'lease_token': SECRET, 'direction': '\ud800'}),
    ('reset-software-stop', {'confirmed_stationary': SECRET}),
    ('simulation/reset-software-stop', {'confirmed_stationary': False, 'private': SECRET}),
])
def test_invalid_robot_payload_is_fixed_redacted_response(client, path, payload):
    response = client.post('/api/v1/robot/' + path, headers=AUTH,
                           content=json.dumps(payload),)
    assert response.status_code == 422
    assert response.json() == {'detail': 'robot request failed validation'}
    assert response.headers['cache-control'] == 'no-store'
    assert SECRET not in response.text
    assert 'lease_token' not in response.text


def test_bad_json_and_private_query_are_not_echoed(client):
    for response in (
        client.post('/api/v1/robot/command', headers={**AUTH, 'Content-Type': 'application/json'},
                    content='{"lease_token":"' + SECRET + '",'),
        client.get('/api/v1/robot/audit', params={'before_id': SECRET}, headers=AUTH),
    ):
        assert response.status_code == 422
        assert response.json() == {'detail': 'robot request failed validation'}
        assert SECRET not in response.text
        assert response.headers['cache-control'] == 'no-store'


def test_success_and_handled_errors_do_not_allow_storage(client):
    status = client.get('/api/v1/robot/status')
    lease = client.post('/api/v1/robot/lease', headers=AUTH)
    assert status.status_code == lease.status_code == 200
    assert isinstance(lease.json()['lease_token'], str)
    responses = [status, lease,
                 client.get('/api/v1/robot/audit', headers=AUTH),
                 client.get('/api/v1/robot/audit'),
                 client.post('/api/v1/robot/lease', headers=AUTH),
                 client.post('/api/v1/robot/lease', headers={**AUTH, 'Origin': 'https://attacker.example'}),
                 client.get('/api/v1/robot/unknown')]
    assert [response.status_code for response in responses] == [200, 200, 200, 403, 409, 403, 404]
    assert all(response.headers['cache-control'] == 'no-store' for response in responses)


def test_unrelated_routes_keep_normal_validation_contract(client):
    response = client.get('/api/v1/events', params={'limit': 'not-integer'})
    assert response.status_code == 422
    assert isinstance(response.json()['detail'], list)
    assert client.get('/api/v1/robotics/not-a-robot-route').headers.get('cache-control') != 'no-store'
