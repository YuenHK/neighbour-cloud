"""Shutdown cleanup tests: fake workers and simulated transports only."""
from types import SimpleNamespace

import pytest

from edge_hub import robot_control
from edge_hub.robot_control import ControlError, RobotCommand, RobotController, SimulatedTransport


def moving_controller(transport=None):
    controller = RobotController(transport=transport, clock=lambda: 1000, wall_clock=lambda: 1000)
    token = controller.acquire()['lease_token']
    controller.command(RobotCommand(lease_token=token, seq=0, issued_at_ms=1000000,
                                    ttl_ms=500, direction='forward'))
    return controller


def test_join_exception_cannot_skip_stop_or_lease_revocation():
    controller = moving_controller()

    def broken_join(timeout):
        assert timeout == 1 and controller.stopping.is_set()
        raise RuntimeError('join failed')

    controller.thread = SimpleNamespace(join=broken_join)
    try:
        with pytest.raises(RuntimeError, match='join failed'):
            controller.shutdown()
        status = controller.status()
        assert status['direction'] == controller.transport.direction == 'stop'
        assert not status['lease_active']
        assert controller.motion_deadline == controller.lease_deadline == 0
        assert controller.audit()[0]['reason'] == 'backend_shutdown'
    finally:
        controller.thread = None
        controller.close()


def test_shutdown_from_worker_does_not_join_itself(monkeypatch):
    controller = moving_controller()

    def forbidden_join(timeout):
        pytest.fail('must not join the current worker')

    worker = SimpleNamespace(join=forbidden_join)
    controller.thread = worker
    monkeypatch.setattr(robot_control.threading, 'current_thread', lambda: worker)
    try:
        controller.shutdown()
        assert controller.transport.direction == 'stop'
        assert not controller.status()['lease_active']
        assert controller.thread is worker  # No false claim that the worker has exited.
        assert controller.stopping.is_set()
    finally:
        controller.thread = None
        controller.close()


def test_join_failure_and_transport_stop_failure_persist_fault():
    class BrokenStop(SimulatedTransport):
        def stop(self):
            raise RuntimeError('private transport error')

    controller = moving_controller(BrokenStop())

    def broken_join(timeout):
        raise RuntimeError('join failed')

    controller.thread = SimpleNamespace(join=broken_join)
    try:
        with pytest.raises(RuntimeError, match='join failed'):
            controller.shutdown()
        status = controller.status()
        assert status['state'] == 'fault' and status['reason'] == 'transport_stop_failed'
        assert status['software_stop_latched'] and not status['lease_active']
        assert controller.db.execute('SELECT fault FROM control_safety').fetchone()[0] == 1
        assert status['hardware_acceptance'] is False
    finally:
        controller.thread = None
        controller.close()


def test_audit_failure_stops_transport_before_any_join():
    controller = moving_controller()
    controller.db.close()

    def broken_join(timeout):
        pytest.fail('audit failure must propagate before waiting for the worker')

    controller.thread = SimpleNamespace(join=broken_join)
    with pytest.raises(ControlError, match='control_audit_unavailable'):
        controller.shutdown()
    assert controller.transport.direction == 'stop'
    assert controller.status()['state'] == 'fault'
    assert not controller.status()['lease_active']
