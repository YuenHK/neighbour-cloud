"""Injected watchdog failures, fake worker and simulated transport only."""
import pytest

from edge_hub import robot_control
from edge_hub.robot_control import ControlError, RobotCommand, RobotController, SimulatedTransport


class CapturedWorker:
    def __init__(self, *, target, daemon):
        self.target = target

    def start(self):
        pass

    def is_alive(self):
        return False


def inject_fault(controller, monkeypatch):
    token = controller.acquire()['lease_token']
    controller.command(RobotCommand(lease_token=token, seq=0, issued_at_ms=1000000,
                                    ttl_ms=500, direction='forward'))
    monkeypatch.setattr(robot_control.threading, 'Thread', CapturedWorker)
    controller.start()
    original_tick = controller.tick

    def broken_tick():
        raise RuntimeError('private watchdog internals')

    controller.tick = broken_tick
    try:
        controller.thread.target()  # Run captured worker synchronously, not a real thread.
    finally:
        controller.tick = original_tick
    return token


@pytest.mark.parametrize('stop_fails', [False, True])
def test_unexpected_watchdog_fault_survives_abrupt_database_reopen(monkeypatch, tmp_path, stop_fails):
    class Transport(SimulatedTransport):
        def stop(self):
            if stop_fails:
                raise RuntimeError('private SDK stop details')
            super().stop()

    path = tmp_path / 'control.sqlite3'
    controller = RobotController(path, transport=Transport(), clock=lambda: 1000, wall_clock=lambda: 1000)
    token = inject_fault(controller, monkeypatch)
    try:
        status = controller.status()
        assert status['state'] == 'fault' and status['software_stop_latched']
        assert not status['lease_active'] and status['direction'] == 'stop'
        assert controller.motion_deadline == controller.lease_deadline == 0
        assert controller.stopping.is_set()
        audit = controller.audit()[0]
        assert audit['action'] == 'watchdog_failure'
        assert audit['reason'] == ('watchdog_stop_failed' if stop_fails else 'watchdog_failure')
        assert token not in str(controller.audit())
        assert 'private' not in str(controller.audit())
    finally:
        controller.db.close()  # Do not let normal shutdown manufacture the durable fault.
    reopened = RobotController(path)
    try:
        assert reopened.status()['state'] == 'fault'
        with pytest.raises(ControlError, match='on_site'):
            reopened.reset_software_stop()
        assert reopened.status()['hardware_acceptance'] is False
    finally:
        reopened.close()


def test_failed_watchdog_audit_stays_faulted_without_claiming_durable_write(monkeypatch, tmp_path):
    controller = RobotController(tmp_path / 'control.sqlite3', clock=lambda: 1000, wall_clock=lambda: 1000)
    controller.db.execute("CREATE TRIGGER fail_watchdog BEFORE INSERT ON control_audit "
                          "WHEN NEW.action='watchdog_failure' BEGIN SELECT RAISE(ABORT,'no'); END")
    controller.db.commit()
    try:
        inject_fault(controller, monkeypatch)
        status = controller.status()
        assert status['state'] == 'fault' and status['reason'] == 'audit_failure'
        assert controller.transport.direction == 'stop' and controller.stopping.is_set()
        assert not status['lease_active']
        assert controller.db.execute('SELECT fault FROM control_safety').fetchone()[0] == 0
        assert not any(row['action'] == 'watchdog_failure' for row in controller.audit())
        with pytest.raises(ControlError, match='latched'):
            controller.acquire()
    finally:
        controller.db.close()
