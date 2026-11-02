import asyncio
import importlib

import pytest
from fastapi.testclient import TestClient

from edge_hub.event_request import RobotBodyLimitMiddleware
from edge_hub.robot_control import RobotController


def invoke(messages, *, headers=(), max_bytes=12):
    called, sent = [], []
    pending = iter(messages)

    async def receive():
        return next(pending)

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        called.extend([await receive(), await receive()])

    asyncio.run(RobotBodyLimitMiddleware(app, max_bytes=max_bytes)(
        {'type': 'http', 'method': 'POST', 'path': '/api/v1/robot/command', 'headers': headers}, receive, send))
    return called, sent


@pytest.mark.parametrize('headers,status', [
    ([(b'content-length', b'9999999999999')], 413),
    ([(b'content-length', b'-1')], 400),
    ([(b'Content-Length', b'1'), (b'content-length', b'1')], 400),
])
def test_bad_declared_length_does_not_receive_or_parse(headers, status):
    called, sent = invoke([], headers=headers)
    assert not called and sent[0]['status'] == status
    assert (b'cache-control', b'no-store') in sent[0]['headers']
    assert b'robot' in sent[-1]['body']


@pytest.mark.parametrize('headers', [[], [(b'content-length', b'1')]])
def test_chunked_actual_bytes_are_bounded_despite_header(headers):
    called, sent = invoke([{'type': 'http.request', 'body': b'private!', 'more_body': True},
                           {'type': 'http.request', 'body': b'private!'}], headers=headers)
    assert not called and sent[0]['status'] == 413
    assert b'private' not in sent[-1]['body']


def test_exact_limit_replays_once_then_real_disconnect():
    called, sent = invoke([{'type': 'http.request', 'body': b'{}' + b' ' * 10},
                           {'type': 'http.disconnect'}])
    assert called == [{'type': 'http.request', 'body': b'{}' + b' ' * 10, 'more_body': False},
                      {'type': 'http.disconnect'}]
    assert not sent


@pytest.mark.parametrize('empty_frames', [False, True])
def test_slow_or_endless_empty_body_times_out_without_downstream(empty_frames):
    sent = []

    async def receive():
        if not empty_frames:
            await asyncio.sleep(1)
        return {'type': 'http.request', 'body': b'', 'more_body': True}

    async def send(message):
        sent.append(message)

    async def app(*args):
        raise AssertionError('expired body must not reach control API')

    asyncio.run(RobotBodyLimitMiddleware(app, timeout_seconds=.01)(
        {'type': 'http', 'method': 'POST', 'path': '/api/v1/robot/software-stop'}, receive, send))
    assert sent[0]['status'] == 408


@pytest.mark.parametrize('scope', [
    {'type': 'websocket'}, {'type': 'http', 'method': 'GET', 'path': '/api/v1/robot/status'},
    {'type': 'http', 'method': 'POST', 'path': '/api/v1/robotics'},
    {'type': 'http', 'method': 'POST', 'path': '/api/v1/events'},
])
def test_other_routes_do_not_receive_robot_budget(scope):
    called = []

    async def app(actual, receive, send):
        called.append(actual)

    asyncio.run(RobotBodyLimitMiddleware(app)(scope, None, None))
    assert called == [scope]


def test_api_budget_rejections_are_private_without_lease_or_audit_change(monkeypatch):
    hub = importlib.import_module('edge_hub.app')
    controller = RobotController()
    monkeypatch.setattr(hub, 'robot_control', controller)
    monkeypatch.setattr(hub, 'OPERATOR_KEY', 'budget-fixture-operator')
    headers = {'X-Operator-Key': 'budget-fixture-operator', 'Content-Type': 'application/json',
               'Origin': 'http://127.0.0.1:4173'}
    try:
        client = TestClient(hub.app)
        for path in ('lease', 'command', 'simulation/command', 'software-stop'):
            response = client.post('/api/v1/robot/' + path, headers=headers, content=b'private' * 1200)
            assert response.status_code == 413
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['access-control-allow-origin'] == 'http://127.0.0.1:4173'
            assert 'private' not in response.text
        for body in (b'[' * 17 + b']' * 17, b'\xff', b'{\x00}'):
            response = client.post('/api/v1/robot/command', headers=headers, content=body)
            assert response.status_code == 400
            assert 'robot JSON' in response.text
        assert controller.audit() == [] and controller.lease is None
        assert controller.direction == 'stop' and not controller.stop_latched
        # Exact valid budget is accepted; this only acquires a simulated lease.
        response = client.post('/api/v1/robot/lease', headers=headers, content=b'{}' + b' ' * 8190)
        assert response.status_code == 200
        assert controller.direction == 'stop'
    finally:
        controller.close()
