import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from edge_hub.ep_acceptance import EpAcceptance, ep_acceptance_router
from edge_hub.ep_console import EpBroker
from edge_hub.ep_fleet import EpFleetBroker
from edge_hub.robot_control import ControlError


class FakeBroker:
    def __init__(self):
        self.calls = []
        self.connection = 'not_connected'
        self.prepared = False
        self.control = None

    def request(self, operation, payload=None):
        self.calls.append((operation, payload))
        if operation == 'connect':
            self.connection = 'connected'
        if operation == 'prepare-control':
            self.prepared = True
        if operation == 'reset-stop':
            self.control = {'state': 'idle', 'software_stop_latched': False, 'lease_active': False}
        return {'connection': self.connection, 'control': self.control, 'prepared_idle': self.prepared}

    def close(self):
        self.calls.append(('disconnect', None))
        self.connection = 'not_connected'
        self.prepared = False


@pytest.fixture
def setup(tmp_path):
    (tmp_path / '.runtime').mkdir()
    (tmp_path / '.runtime/ep-safety-hold.json').write_text('{')
    fleet = EpFleetBroker(tmp_path)
    for index in (1, 2):
        item = fleet.register(f'192.168.99.{index}')
        item['known_sn'] = f'SYNTHETIC-{index}'
    broker = FakeBroker()
    acceptance = EpAcceptance(fleet, broker)
    return fleet, broker, acceptance


def test_loading_and_polling_only_passive_status_never_connects(setup):
    fleet, broker, acceptance = setup
    for _ in range(3):
        state = acceptance.state()
        assert state['auto_reconnect'] is False and state['movement_enabled'] is False
    assert broker.calls == [('status', None)] * 3
    assert fleet.monitor_thread is None


def test_real_passive_acceptance_broker_does_not_launch_worker(setup):
    fleet, _, _ = setup
    acceptance = EpAcceptance(fleet)
    acceptance.broker._start = Mock(side_effect=AssertionError('no launch'))
    assert acceptance.broker.acceptance_only
    assert acceptance.state()['connection'] == 'not_connected'
    assert acceptance.broker.process is None
    acceptance.broker._start.assert_not_called()


def test_manual_connect_uses_saved_identity_and_only_one_target(setup):
    fleet, broker, acceptance = setup
    acceptance.connect('ep-1')
    assert broker.calls == [('connect', {'ip': '192.168.99.1', 'expected_sn': 'SYNTHETIC-1', 'confirmed': True})]
    with pytest.raises(ControlError):
        acceptance.connect('ep-2')
    assert len(broker.calls) == 1
    assert fleet.safety_hold()
    acceptance.disconnect()
    acceptance.connect('ep-2')
    assert acceptance.selected == 'ep-2'


def test_unknown_target_or_normal_worker_prevents_connect(setup):
    fleet, broker, acceptance = setup
    with pytest.raises(ControlError):
        acceptance.connect('ep-3')
    fleet.process = Mock()
    fleet.process.poll.return_value = None
    with pytest.raises(ControlError):
        acceptance.connect('ep-1')
    assert broker.calls == []


def test_stage_three_requires_separate_prepare_and_uses_original_control_store(setup):
    _, broker, acceptance = setup
    acceptance.connect('ep-1', 3)
    assert acceptance.started_at is None and broker.device_id is None
    assert broker.acceptance_prepare
    assert [op for op, _ in broker.calls] == ['connect']
    acceptance.prepare()
    assert acceptance.started_at is not None
    assert acceptance.state()['prepared_idle']
    with pytest.raises(ControlError):
        acceptance.prepare()
    assert [op for op, _ in broker.calls].count('prepare-control') == 1
    acceptance.disconnect()
    acceptance.connect('ep-2', 3)
    assert broker.device_id == 'ep-2'


def test_stage_two_cannot_prepare_and_stage_three_still_cannot_lease_or_drive(setup):
    fleet, _, acceptance = setup
    with pytest.raises(ControlError):
        acceptance.prepare()
    acceptance.connect('ep-1')
    with pytest.raises(ControlError):
        acceptance.prepare()
    broker = EpBroker(fleet.root, acceptance_only=True)
    broker.acceptance_prepare = True
    broker._start = Mock(side_effect=AssertionError('no SDK launch'))
    for op in ['lease', 'command', 'gimbal-follow', 'video-start', 'speed']:
        with pytest.raises(ControlError):
            broker.request(op)
    broker._start.assert_not_called()


def test_prepared_worker_launch_keeps_role_and_selected_primary_store(setup, monkeypatch):
    fleet, _, _ = setup
    python = fleet.root / '.runtime/ep-sdk/venv/Scripts/python.exe'
    source = fleet.root / '.runtime/ep-sdk/source/src/robomaster/robot.py'
    for path in (python, source):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    process = Mock()
    process.stdout = []
    launch = Mock(return_value=process)
    monkeypatch.setattr('edge_hub.ep_console.subprocess.Popen', launch)
    broker = EpBroker(fleet.root, sdk_port=12008, acceptance_only=True)
    broker.acceptance_prepare = True
    broker._start()
    args = launch.call_args.args[0]
    assert '--acceptance-only' in args and '--acceptance-prepare' in args
    assert args[args.index('--sdk-port') + 1] == '12008'
    assert '--device-id' not in args  # primary must use original ep-control.sqlite3


def test_cancel_during_prepare_closes_late_prepared_session(setup):
    _, broker, acceptance = setup
    acceptance.connect('ep-1', 3)
    started, finish = threading.Event(), threading.Event()
    original = broker.request
    def delayed(operation, payload=None):
        started.set()
        assert finish.wait(2)
        return original(operation, payload)
    broker.request = delayed
    thread = threading.Thread(target=acceptance.prepare)
    thread.start()
    assert started.wait(2)
    acceptance.disconnect()
    finish.set()
    thread.join(2)
    assert not thread.is_alive()
    assert acceptance.started_at is None and acceptance.selected is None
    assert broker.connection == 'not_connected'


def test_disconnect_during_setup_closes_late_connection_without_retry(setup):
    _, broker, acceptance = setup
    started, finish = threading.Event(), threading.Event()
    original = broker.request
    def delayed(operation, payload=None):
        started.set()
        assert finish.wait(2)
        return original(operation, payload)
    broker.request = delayed
    result = []
    thread = threading.Thread(target=lambda: result.append(acceptance.connect('ep-1')))
    thread.start()
    assert started.wait(2)
    assert acceptance.disconnect()['connection'] == 'disconnecting'
    finish.set()
    thread.join(2)
    assert not thread.is_alive()
    assert result[0]['cancelled']
    assert broker.connection == 'not_connected' and acceptance.selected is None
    assert [op for op, _ in broker.calls] == ['connect', 'disconnect']


@pytest.mark.parametrize('operation', [
    'prepare-control', 'lease', 'command', 'stop', 'reset-stop', 'heartbeat', 'health',
    'gimbal-follow', 'gimbal-start', 'gimbal-target', 'gimbal-stop', 'speed',
    'qr', 'qr-status', 'video-start', 'video-frame', 'video-stop', 'video-heartbeat',
])
def test_acceptance_broker_blocks_every_active_operation_before_worker(setup, operation):
    fleet, _, _ = setup
    broker = EpBroker(fleet.root, acceptance_only=True)
    broker._start = Mock(side_effect=AssertionError('no worker'))
    with pytest.raises(ControlError) as error:
        broker.request(operation)
    assert error.value.status == 423
    broker._start.assert_not_called()


def test_http_entry_is_local_and_requires_explicit_confirmed_post(setup):
    _, broker, acceptance = setup
    app = FastAPI()
    def authorize(key):
        if key != 'synthetic-local-key':
            raise HTTPException(403)
    app.include_router(ep_acceptance_router(acceptance, authorize,
                       Path(__file__).resolve().parents[1] / 'edge_hub/static'))
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    headers = {'X-Operator-Key': 'synthetic-local-key'}
    assert client.get('/ep-acceptance').status_code == 200
    assert client.get('/ep-idle-acceptance').status_code == 200
    assert broker.calls == []
    assert client.get('/api/v1/robot/ep/acceptance/status', headers=headers).status_code == 200
    assert [op for op, _ in broker.calls] == ['status']
    route = '/api/v1/robot/ep/acceptance/connect'
    assert client.post(route, headers=headers, json={'device_id': 'ep-1'}).status_code == 422
    assert client.post(route, headers=headers, json={
        'device_id': 'ep-1', 'confirmed_stationary': True, 'ip': '192.168.99.99'}).status_code == 422
    assert client.post(route, json={'device_id': 'ep-1', 'confirmed_stationary': True}).status_code == 403
    assert client.post(route, headers={**headers, 'Origin': 'http://other.invalid'},
                       json={'device_id': 'ep-1', 'confirmed_stationary': True}).status_code == 403
    assert all(op == 'status' for op, _ in broker.calls)
    assert client.post(route, headers=headers, json={
        'device_id': 'ep-1', 'confirmed_stationary': True}).status_code == 200
    assert client.post('/api/v1/robot/ep/acceptance/lease', headers=headers, json={}).status_code == 404
    prepare_route = '/api/v1/robot/ep/acceptance/prepare'
    assert client.post(prepare_route, headers=headers, json={}).status_code == 422
    assert client.post(prepare_route, headers=headers, json={
        'confirmed_gimbal_recenter': True}).status_code == 423
    acceptance.disconnect()
    assert client.post(route, headers=headers, json={
        'device_id': 'ep-1', 'confirmed_stationary': True, 'stage': 3}).status_code == 200
    assert client.post(prepare_route, headers=headers, json={
        'confirmed_gimbal_recenter': True}).status_code == 200
    reset_route = '/api/v1/robot/ep/acceptance/reset-stop'
    assert client.post(reset_route, headers=headers, json={}).status_code == 422
    assert client.post(reset_route, headers=headers, json={'confirmed_stationary': False}).status_code == 422


def test_manual_reset_only_clears_ordinary_stop_without_prepare_or_timer(setup):
    _, broker, acceptance = setup
    acceptance.connect('ep-1', 3)
    acceptance.prepare_attempted = True
    broker.control = {'state': 'safe_stop', 'software_stop_latched': True, 'lease_active': False}
    result = acceptance.reset_stop()
    assert result['control']['software_stop_latched'] is False
    assert acceptance.prepare_attempted is False and acceptance.started_at is None
    assert [op for op, _ in broker.calls] == ['connect', 'status', 'reset-stop']
    assert broker.calls[-1][1] == {'confirmed_stationary': True}


@pytest.mark.parametrize('stage,state,latched,lease', [
    (2, 'safe_stop', True, False), (3, 'fault', True, False),
    (3, 'idle', False, False), (3, 'safe_stop', True, True),
])
def test_reset_refuses_wrong_stage_fault_missing_stop_or_lease(setup, stage, state, latched, lease):
    _, broker, acceptance = setup
    acceptance.connect('ep-1', stage)
    broker.control = {'state': state, 'software_stop_latched': latched, 'lease_active': lease}
    with pytest.raises(ControlError):
        acceptance.reset_stop()
    assert all(op != 'reset-stop' for op, _ in broker.calls)


def test_stage_four_launches_only_short_role_and_keeps_generic_control_closed(setup):
    fleet, broker, acceptance = setup
    acceptance.connect('ep-2', 4)
    assert broker.acceptance_short_press and broker.acceptance_prepare
    assert broker.device_id == 'ep-2'
    acceptance.short_press('short-press-start', {'synthetic': True})
    assert broker.calls[-1][0] == 'short-press-start'
    guarded = EpBroker(fleet.root, acceptance_only=True)
    guarded.acceptance_prepare = guarded.acceptance_short_press = True
    guarded._start = Mock(side_effect=AssertionError('do not start SDK'))
    for operation in ['lease', 'command', 'speed', 'gimbal-follow', 'video-start']:
        with pytest.raises(ControlError):
            guarded.request(operation)
    guarded._start.assert_not_called()


@pytest.mark.parametrize('stage', [2, 3])
def test_short_press_is_unavailable_in_earlier_stages(setup, stage):
    _, broker, acceptance = setup
    acceptance.connect('ep-2', stage)
    before = list(broker.calls)
    with pytest.raises(ControlError):
        acceptance.short_press('short-press-start', {})
    assert broker.calls == before


def test_short_release_is_not_blocked_by_changed_pairing_or_hold_state(setup):
    fleet, broker, acceptance = setup
    acceptance.connect('ep-2', 4)
    acceptance.pairing_active = lambda: True
    (fleet.root / '.runtime/ep-safety-hold.json').unlink()  # disposable test root only
    with pytest.raises(ControlError):
        acceptance.short_press('short-press-start', {})
    acceptance.short_press('short-press-release', {'synthetic': True})
    assert broker.calls[-1][0] == 'short-press-release'


def test_short_http_validates_clear_path_and_rejects_extra_direction_or_speed(setup):
    _, broker, acceptance = setup
    app = FastAPI()
    app.include_router(ep_acceptance_router(acceptance, lambda _: None,
                       Path(__file__).resolve().parents[1] / 'edge_hub/static'))
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    assert client.get('/ep-short-press-acceptance').status_code == 200
    acceptance.connect('ep-2', 4)
    route = '/api/v1/robot/ep/acceptance/short-press-start'
    data = {'session_id': 'a' * 32, 'press_id': 'b' * 32, 'issued_at_ms': 1000,
            'confirmed_clear_path': True}
    for invalid in [{**data, 'confirmed_clear_path': False}, {**data, 'direction': 'backward'},
                    {**data, 'speed': 4}]:
        assert client.post(route, json=invalid).status_code == 422
    assert all(op != 'short-press-start' for op, _ in broker.calls)
    assert client.post(route, json=data).status_code == 200
    assert broker.calls[-1] == ('short-press-start', data)


def test_release_check_role_and_minimal_stop_receipt_survive_disconnect(setup):
    _, broker, acceptance = setup
    acceptance.connect('ep-2', 5)
    assert broker.acceptance_release_check and broker.acceptance_short_press
    result = {'short_press_used': True, 'short_press_stop_origin': 'release', 'short_press_max_ms': 500,
              'control': {'state': 'safe_stop', 'direction': 'stop', 'lease_active': False}}
    original = broker.request
    broker.request = lambda op, payload=None: result if op == 'short-press-release' else original(op, payload)
    acceptance.short_press('short-press-release', {})
    acceptance.disconnect()
    receipt = acceptance.state()['last_short_receipt']
    assert receipt['stage'] == 5 and receipt['stop_origin'] == 'release'
    assert receipt['physical_stop_verified'] is False
    assert 'session_id' not in receipt and 'lease_token' not in receipt


def test_idle_motor_role_uses_original_store_and_is_not_retained_next_session(setup):
    _, broker, acceptance = setup
    acceptance.connect('ep-2', 6)
    assert broker.acceptance_idle_motor and broker.acceptance_release_check
    assert broker.acceptance_short_press and broker.acceptance_prepare
    assert broker.device_id == 'ep-2'
    assert [op for op, _ in broker.calls] == ['connect']
    acceptance.motor('motor-release', {'synthetic': True})
    assert broker.calls[-1] == ('motor-release', {'synthetic': True})
    acceptance.disconnect()
    acceptance.connect('ep-1', 3)
    assert not broker.acceptance_idle_motor and not broker.acceptance_release_check
    with pytest.raises(ControlError):
        acceptance.motor('motor-activate', {})


@pytest.mark.parametrize('operation', ['motor-release', 'motor-activate'])
def test_old_broker_roles_reject_motor_operations_before_start(setup, operation):
    fleet, _, _ = setup
    broker = EpBroker(fleet.root, acceptance_only=True)
    broker._start = Mock(side_effect=AssertionError('must not launch'))
    for stage in (2, 3, 4, 5):
        broker.acceptance_prepare = stage >= 3
        broker.acceptance_short_press = stage >= 4
        broker.acceptance_release_check = stage == 5
        with pytest.raises(ControlError):
            broker.request(operation, {})
    broker._start.assert_not_called()


def test_idle_motor_http_strict_confirmation_identity_and_stage(setup):
    _, broker, acceptance = setup
    app = FastAPI()
    app.include_router(ep_acceptance_router(acceptance, lambda _: None,
                       Path(__file__).resolve().parents[1] / 'edge_hub/static'))
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    assert client.get('/ep-idle-motor-acceptance').status_code == 200
    assert broker.calls == []
    route = '/api/v1/robot/ep/acceptance/motor-release'
    data = {'session_id': 'a' * 32, 'stop_id': 'b' * 32, 'confirmed_stationary': True}
    assert client.post(route, json=data).status_code == 423
    acceptance.connect('ep-2', 6)
    for invalid in ({**data, 'confirmed_stationary': False}, {**data, 'mode': 0},
                    {**data, 'session_id': 'old'}, {'confirmed_stationary': True}):
        assert client.post(route, json=invalid).status_code == 422
    assert not any(op == 'motor-release' for op, _ in broker.calls)
    assert client.post(route, json=data).status_code == 200
    assert broker.calls[-1] == ('motor-release', data)
    activation = {'session_id': 'a' * 32, 'press_id': 'b' * 32,
                  'issued_at_ms': 1000, 'confirmed_clear_path': True}
    route = '/api/v1/robot/ep/acceptance/motor-activate'
    assert client.post(route, json={**activation, 'speed': 4}).status_code == 422
    assert client.post(route, json=activation).status_code == 200
    assert broker.calls[-1] == ('motor-activate', activation)
    acceptance.pairing_active = lambda: True
    assert client.post(route, json=activation).status_code == 423


def test_idle_motor_worker_flag_is_explicit_and_keeps_all_restrictions(setup, monkeypatch):
    fleet, _, _ = setup
    for relative in ('.runtime/ep-sdk/venv/Scripts/python.exe', '.runtime/ep-sdk/source/src/robomaster/robot.py'):
        path = fleet.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    broker = EpBroker(fleet.root, 'ep-2', 12008, acceptance_only=True)
    broker.acceptance_prepare = broker.acceptance_short_press = True
    broker.acceptance_release_check = broker.acceptance_idle_motor = True
    process = Mock()
    process.stdout = []
    launch = Mock(return_value=process)
    monkeypatch.setattr('edge_hub.ep_console.subprocess.Popen', launch)
    broker._start()
    args = launch.call_args.args[0]
    for flag in ('--acceptance-only', '--acceptance-prepare', '--acceptance-short-press',
                 '--acceptance-release-check', '--acceptance-idle-motor'):
        assert flag in args
    assert args[args.index('--device-id') + 1] == 'ep-2'
    for operation in ('lease', 'command', 'speed', 'video-start', 'gimbal-start', 'qr'):
        with pytest.raises(ControlError):
            broker.request(operation, {})


def test_automatic_connect_is_bounded_and_never_prepares(setup, monkeypatch):
    _, broker, acceptance = setup
    now = [100.]
    monkeypatch.setattr('edge_hub.ep_acceptance.time.monotonic', lambda: now[0])
    original = broker.request
    def failed(operation, payload=None):
        if operation == 'connect':
            broker.calls.append((operation, payload))
            broker.connection = 'not_connected'
            raise ControlError('timeout', 503)
        result = original(operation, payload)
        return {**result, 'last_connection_error': {'code': 'handshake_timeout'}}
    broker.request = failed
    for _ in range(3):
        with pytest.raises(ControlError):
            acceptance.connect('ep-2', 6, automatic=True)
        now[0] += 6
    assert acceptance.auto_attempts == 3
    with pytest.raises(ControlError):
        acceptance.connect('ep-2', 6, automatic=True)
    assert [op for op, _ in broker.calls].count('connect') == 3
    assert not any(op in {'prepare-control', 'reset-stop', 'motor-release', 'motor-activate', 'short-press-start'}
                   for op, _ in broker.calls)


@pytest.mark.parametrize('connection,prepared,error', [
    ('connected', False, 'handshake_timeout'), ('not_connected', True, 'handshake_timeout'),
    ('not_connected', False, 'identity_mismatch'), ('connecting', False, 'handshake_timeout'),
])
def test_auto_retry_never_interrupts_connected_prepared_or_wrong_identity(setup, connection, prepared, error):
    _, broker, acceptance = setup
    acceptance.connect('ep-2', 6)
    broker.connection, broker.prepared = connection, prepared
    original = broker.request
    broker.request = lambda op, payload=None: {**original(op, payload), 'last_connection_error': {'code': error}}
    before = len(broker.calls)
    with pytest.raises(ControlError):
        acceptance.connect('ep-2', 6, automatic=True)
    assert broker.calls[before:] == [('status', None)]


def test_auto_connect_http_requires_explicit_opt_in_and_never_starts_on_get(setup):
    _, broker, acceptance = setup
    app = FastAPI()
    app.include_router(ep_acceptance_router(acceptance, lambda _: None,
                       Path(__file__).resolve().parents[1] / 'edge_hub/static'))
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    assert client.get('/ep-idle-motor-acceptance').status_code == 200
    assert broker.calls == []
    body = {'device_id': 'ep-2', 'stage': 6, 'confirmed_stationary': True, 'confirmed_auto_connect': True}
    route = '/api/v1/robot/ep/acceptance/connect-auto'
    for invalid in ({**body, 'confirmed_auto_connect': False}, {**body, 'stage': 5},
                    {**body, 'prepare': True}, {'device_id': 'ep-2', 'stage': 6, 'confirmed_stationary': True}):
        assert client.post(route, json=invalid).status_code == 422
    assert broker.calls == []
    assert client.post(route, json=body).status_code == 200
    assert [op for op, _ in broker.calls] == ['connect']
    assert acceptance.auto_attempts == 1


def test_auto_retry_rate_limit_does_not_close_or_connect_again(setup, monkeypatch):
    _, broker, acceptance = setup
    monkeypatch.setattr('edge_hub.ep_acceptance.time.monotonic', lambda: 100.)
    acceptance.connect('ep-2', 6, automatic=True)
    before = len(broker.calls)
    with pytest.raises(ControlError) as error:
        acceptance.connect('ep-2', 6, automatic=True)
    assert error.value.status == 409
    assert len(broker.calls) == before
    with pytest.raises(ControlError):
        acceptance.connect('ep-1', 6, automatic=True)
    assert len(broker.calls) == before
