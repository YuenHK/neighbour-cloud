import time

from fastapi.testclient import TestClient

from edge_hub import app as hub
from edge_hub.robot_control import RobotController


def test_console_has_separate_page_and_no_hardware_switch():
    client = TestClient(hub.app)
    response = client.get('/simulation-control', follow_redirects=False)
    assert response.status_code == 307
    assert response.headers['location'] == '/admin#settings'
    assert response.headers['cache-control'] == 'no-store'
    script = client.get('/assets/simulation-control.js')
    assert script.status_code == 200
    assert script.headers['x-content-type-options'] == 'nosniff'
    assert '/api/v1/robot/simulation/' in script.text


def test_simulation_routes_require_operator_and_reject_non_simulated_transport(monkeypatch):
    client = TestClient(hub.app)
    assert client.post('/api/v1/robot/simulation/lease').status_code == 403
    assert client.post('/api/v1/robot/simulation/lease', headers={
        'X-Operator-Key': 'unit-test-operator-only', 'Origin': 'https://untrusted.example'}).status_code == 403
    monkeypatch.setattr(hub.robot_control.transport, 'mode', 'dji-ep-sdk-unverified')
    response = client.post('/api/v1/robot/simulation/lease',
                           headers={'X-Operator-Key': 'unit-test-operator-only'})
    assert response.status_code == 409


def test_simulation_console_api_release_and_reset_are_stop_first(monkeypatch):
    controller = RobotController()
    monkeypatch.setattr(hub, 'robot_control', controller)
    client = TestClient(hub.app)
    headers = {'X-Operator-Key': 'unit-test-operator-only'}
    prefix = '/api/v1/robot/simulation/'
    try:
        token = client.post(prefix + 'lease', headers=headers, json={}).json()['lease_token']
        command = {'lease_token': token, 'seq': 0, 'issued_at_ms': int(time.time() * 1000),
                   'ttl_ms': 300, 'direction': 'forward'}
        assert client.post(prefix + 'command', headers=headers, json=command).json()['direction'] == 'forward'
        command.update(seq=1, direction='stop')
        assert client.post(prefix + 'command', headers=headers, json=command).json()['direction'] == 'stop'
        assert client.get(prefix + 'status').json()['lease_active'] is False
        assert client.post(prefix + 'software-stop', headers=headers, json={}).json()['software_stop_latched']
        assert client.post(prefix + 'lease', headers=headers, json={}).status_code == 423
        assert client.post(prefix + 'reset-software-stop', headers=headers,
                           json={'confirmed_stationary': False}).status_code == 422
        state = client.post(prefix + 'reset-software-stop', headers=headers,
                            json={'confirmed_stationary': True}).json()
        assert state['direction'] == 'stop' and state['lease_active'] is False
    finally:
        controller.close()


def test_simulation_routes_refuse_even_a_transport_falsely_named_simulation(monkeypatch):
    class NotTheSimulator:
        mode = 'simulation'
        connected = False

        def drive(self, *_):
            raise AssertionError('must not call a non-simulation transport')

        def stop(self):
            raise AssertionError('must not call a non-simulation transport')

    monkeypatch.setattr(hub.robot_control, 'transport', NotTheSimulator())
    client = TestClient(hub.app)
    headers = {'X-Operator-Key': 'unit-test-operator-only'}
    prefix = '/api/v1/robot/simulation/'
    assert client.get(prefix + 'status').status_code == 409
    command = {'lease_token': 'test-invalid-token-but-valid-length', 'seq': 0,
               'issued_at_ms': 1, 'ttl_ms': 300, 'direction': 'forward'}
    for action, payload in [('lease', {}), ('command', command), ('software-stop', {}),
                            ('reset-software-stop', {'confirmed_stationary': True})]:
        assert client.post(prefix + action, headers=headers, json=payload).status_code == 409
