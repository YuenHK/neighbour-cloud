import importlib
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from edge_hub.robot_control import RobotCommand, RobotController


def payload(token):
    return {'lease_token': token, 'seq': 0, 'issued_at_ms': 1000000,
            'ttl_ms': 500, 'direction': 'stop'}


@pytest.mark.parametrize('token', [
    '私' * 20, 'x' * 20 + '\ud800', 'x' * 20 + '\n', 'x' * 20 + '\r',
    'x' * 20 + '\x00', 'x' * 20 + ' ', 'x' * 20 + '+', 'x' * 20 + '/',
    'x' * 20 + '=', 'x' * 19, 'x' * 129,
], ids=['unicode', 'surrogate', 'newline', 'return', 'nul', 'space', 'plus', 'slash',
        'padding', 'short', 'long'])
def test_lease_contract_rejects_non_urlsafe_or_unbounded_tokens(token):
    with pytest.raises(ValidationError):
        RobotCommand(**payload(token))


@pytest.mark.parametrize('token', ['x' * 20, 'x' * 128, 'aB_0-9' * 5])
def test_urlsafe_ascii_contract_boundaries_remain_accepted(token):
    assert RobotCommand(**payload(token)).lease_token == token


@pytest.mark.parametrize('route', ['command', 'simulation/command'])
def test_non_ascii_lease_cannot_crash_api_or_modify_existing_lease(monkeypatch, route):
    hub = importlib.import_module('edge_hub.app')
    controller = RobotController(clock=lambda: 1000., wall_clock=lambda: 1000.)
    monkeypatch.setattr(hub, 'robot_control', controller)
    monkeypatch.setattr(hub, 'OPERATOR_KEY', 'lease-format-test-operator')
    headers = {'X-Operator-Key': 'lease-format-test-operator', 'Content-Type': 'application/json'}
    try:
        token = controller.acquire()['lease_token']
        before = controller.audit()
        client = TestClient(hub.app, raise_server_exceptions=False)
        for invalid in ('私' * 20, 'x' * 20 + '\ud800', 'x' * 20 + '\n'):
            response = client.post('/api/v1/robot/' + route, headers=headers,
                                   content=json.dumps(payload(invalid)))
            assert response.status_code == 422
            assert response.json() == {'detail': 'robot request failed validation'}
            assert response.headers['cache-control'] == 'no-store'
            assert token not in response.text and 'lease_token' not in response.text
        denied = client.post('/api/v1/robot/' + route, headers=headers, json=payload('invalid_ascii_token_1234'))
        assert denied.status_code == 403
        assert denied.json() == {'detail': 'invalid_or_expired_lease'}
        assert controller.lease == token and controller.sequence == -1
        assert controller.audit() == before and not controller.stop_latched
        assert controller.direction == 'stop'
        accepted = client.post('/api/v1/robot/' + route, headers=headers, json=payload(token))
        assert accepted.status_code == 200
        assert accepted.json()['direction'] == 'stop' and not accepted.json()['lease_active']
    finally:
        controller.close()
