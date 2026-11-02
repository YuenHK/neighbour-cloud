"""Watchdog launch failures using simulated transport and fake threads only."""
import pytest

from edge_hub import robot_control
from edge_hub.robot_control import ControlError, RobotCommand, RobotController, SimulatedTransport


class LaunchFailure:
    alive = False

    def __init__(self, **kwargs):
        self.target = kwargs['target']

    def start(self):
        raise RuntimeError('private thread details')

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        assert self.alive, 'must not join an unstarted thread'
        self.alive = False


def moving_controller(path=':memory:', transport=None):
    controller = RobotController(path, transport=transport, clock=lambda: 1000, wall_clock=lambda: 1000)
    token = controller.acquire()['lease_token']
    controller.command(RobotCommand(lease_token=token, seq=0, issued_at_ms=1000000,
                                    ttl_ms=500, direction='forward'))
    return controller, token


@pytest.mark.parametrize('phase', ['constructor', 'start'])
def test_launch_failure_stops_revokes_and_persists_fault(monkeypatch, tmp_path, phase):
    path = tmp_path / 'control.sqlite3'
    controller, token = moving_controller(path)

    def cannot_construct(**kwargs):
        raise RuntimeError('private constructor details')

    monkeypatch.setattr(robot_control.threading, 'Thread',
                        cannot_construct if phase == 'constructor' else LaunchFailure)
    try:
        with pytest.raises(ControlError, match='^control_watchdog_unavailable$') as error:
            controller.start()
        assert error.value.status == 503
        assert error.value.__suppress_context__
        status = controller.status()
        assert status['state'] == 'fault'
        assert status['reason'] == 'watchdog_start_failed'
        assert status['software_stop_latched'] and not status['lease_active']
        assert controller.transport.direction == status['direction'] == 'stop'
        assert controller.motion_deadline == controller.lease_deadline == 0
        assert controller.stopping.is_set() and controller.thread is None
        assert token not in str(controller.audit())
        with pytest.raises(ControlError, match='latched'):
            controller.acquire()
    finally:
        controller.close()
    reopened = RobotController(path)
    try:
        assert reopened.status()['state'] == 'fault'
        with pytest.raises(ControlError, match='on_site'):
            reopened.reset_software_stop()
    finally:
        reopened.close()


def test_live_handle_retained_when_start_raises_after_launch(monkeypatch):
    class LateFailure(LaunchFailure):
        alive = True

    controller, _ = moving_controller()
    monkeypatch.setattr(robot_control.threading, 'Thread', LateFailure)
    try:
        with pytest.raises(ControlError, match='control_watchdog_unavailable'):
            controller.start()
        worker = controller.thread
        assert worker is not None and worker.is_alive()
        assert controller.stopping.is_set()
        controller.start()  # No duplicate thread and no clearing the live worker's stop request.
        assert controller.thread is worker and controller.stopping.is_set()
        assert controller.status()['state'] == 'fault'
    finally:
        controller.close()


def test_stop_failure_during_launch_failure_remains_fault(monkeypatch):
    class BrokenStop(SimulatedTransport):
        def stop(self):
            raise RuntimeError('private transport details')

    controller, _ = moving_controller(transport=BrokenStop())
    monkeypatch.setattr(robot_control.threading, 'Thread', LaunchFailure)
    try:
        with pytest.raises(ControlError, match='control_watchdog_unavailable'):
            controller.start()
        status = controller.status()
        assert status['state'] == 'fault' and status['reason'] == 'transport_stop_failed'
        assert status['software_stop_latched'] and not status['lease_active']
        assert status['hardware_acceptance'] is False
    finally:
        controller.close()


def test_audit_failure_during_launch_failure_is_not_acknowledged(monkeypatch):
    controller, _ = moving_controller()
    controller.db.close()
    monkeypatch.setattr(robot_control.threading, 'Thread', LaunchFailure)
    with pytest.raises(ControlError, match='control_audit_unavailable'):
        controller.start()
    assert controller.status()['state'] == 'fault'
    assert controller.transport.direction == 'stop'
    assert controller.stopping.is_set() and controller.thread is None
