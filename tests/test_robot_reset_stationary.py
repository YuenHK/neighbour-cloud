"""Reset gates using only memory SQLite and simulated transport."""
import importlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from edge_hub.robot_control import ControlError, RobotCommand, RobotController, SimulatedTransport


def moving(controller, token):
    controller.command(RobotCommand(lease_token=token, seq=0, issued_at_ms=1000000,
                                    ttl_ms=500, direction='forward'))


@pytest.mark.parametrize('motion', [False, True])
def test_reset_cannot_steal_active_lease_or_relabel_motion_as_idle(motion):
    controller = RobotController(clock=lambda: 1000., wall_clock=lambda: 1000.)
    try:
        token = controller.acquire()['lease_token']
        if motion:
            moving(controller, token)
        before = (controller.lease, controller.state, controller.direction, controller.reason,
                  controller.sequence, controller.lease_deadline, controller.motion_deadline, controller.audit())
        with pytest.raises(ControlError, match='^control_must_be_stopped_before_reset$') as error:
            controller.reset_software_stop()
        assert error.value.status == 423
        after = (controller.lease, controller.state, controller.direction, controller.reason,
                 controller.sequence, controller.lease_deadline, controller.motion_deadline, controller.audit())
        assert after == before
        assert controller.db.execute('SELECT requires_reset,fault FROM control_safety').fetchone()[:] == (1, 0)
    finally:
        controller.close()


@pytest.mark.parametrize('motion', [False, True])
def test_expired_motion_or_lease_is_stopped_before_reset(motion):
    clock = SimpleNamespace(now=1000.)
    controller = RobotController(clock=lambda: clock.now, wall_clock=lambda: 1000.)
    try:
        token = controller.acquire()['lease_token']
        if motion:
            moving(controller, token)
        clock.now += 3
        state = controller.reset_software_stop()
        assert state['state'] == 'idle' and state['direction'] == 'stop'
        assert state['lease_active'] is False and state['software_stop_latched'] is False
        actions = list(reversed(controller.audit()))
        assert [row['action'] for row in actions[-2:]] == ['stop', 'reset_software_stop']
        assert actions[-2]['reason'] == ('command_timeout' if motion else 'lease_expired')
        assert controller.transport.direction == 'stop'
    finally:
        controller.close()


def test_expiry_stop_fault_cannot_be_cleared_by_same_reset_request():
    class BrokenStop(SimulatedTransport):
        def stop(self):
            raise RuntimeError('private transport details')

    clock = SimpleNamespace(now=1000.)
    controller = RobotController(clock=lambda: clock.now, wall_clock=lambda: 1000., transport=BrokenStop())
    try:
        moving(controller, controller.acquire()['lease_token'])
        clock.now += 1
        with pytest.raises(ControlError, match='^transport_fault_requires_on_site_check$'):
            controller.reset_software_stop()
        assert controller.state == 'fault' and controller.stop_latched
        assert controller.lease is None and controller.direction == 'stop'
        assert controller.db.execute('SELECT requires_reset,fault FROM control_safety').fetchone()[:] == (1, 1)
        assert not any(row['action'] == 'reset_software_stop' for row in controller.audit())
    finally:
        controller.close()


@pytest.mark.parametrize('prefix', ['/api/v1/robot/', '/api/v1/robot/simulation/'])
def test_api_confirmation_cannot_bypass_stop_first_gate(monkeypatch, prefix):
    hub = importlib.import_module('edge_hub.app')
    controller = RobotController(clock=lambda: 1000., wall_clock=lambda: 1000.)
    monkeypatch.setattr(hub, 'robot_control', controller)
    monkeypatch.setattr(hub, 'OPERATOR_KEY', 'stationary-reset-fixture')
    auth = {'X-Operator-Key': 'stationary-reset-fixture'}
    try:
        token = controller.acquire()['lease_token']
        moving(controller, token)
        before = controller.audit()
        client = TestClient(hub.app)
        denied = client.post(prefix + 'reset-software-stop', headers=auth, json={'confirmed_stationary': True})
        assert denied.status_code == 423
        assert denied.json() == {'detail': 'control_must_be_stopped_before_reset'}
        assert token not in denied.text
        assert controller.audit() == before and controller.lease == token
        assert controller.direction == 'forward'
        assert client.post(prefix + 'software-stop', headers=auth).status_code == 200
        accepted = client.post(prefix + 'reset-software-stop', headers=auth, json={'confirmed_stationary': True})
        assert accepted.status_code == 200 and accepted.json()['state'] == 'idle'
        assert accepted.json()['lease_active'] is False and accepted.json()['direction'] == 'stop'
    finally:
        controller.close()
