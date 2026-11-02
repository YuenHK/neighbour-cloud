"""Shutdown motion gate using controlled workers, never a real robot."""
import threading

import pytest

from edge_hub import robot_control
from edge_hub.robot_control import ControlError, RobotCommand, RobotController


def rig():
    controller = RobotController(clock=lambda: 1000, wall_clock=lambda: 1000)
    token = controller.acquire()['lease_token']
    command = RobotCommand(lease_token=token, seq=0, issued_at_ms=1000000,
                           ttl_ms=500, direction='forward')
    return controller, command


def assert_blocked(controller, command):
    for operation in (controller.acquire, lambda: controller.command(command),
                      controller.reset_software_stop):
        with pytest.raises(ControlError, match='^control_backend_stopping$') as error:
            operation()
        assert error.value.status == 503


def test_requests_blocked_during_join_and_after_shutdown():
    controller, command = rig()
    entered, release = threading.Event(), threading.Event()
    errors = []

    class Worker:
        def join(self, timeout):
            entered.set()
            assert release.wait(2)

    controller.thread = Worker()

    def shutdown():
        try:
            controller.shutdown()
        except Exception as error:  # noqa: BLE001 -- surface background failures in the test thread
            errors.append(error)

    runner = threading.Thread(target=shutdown)
    try:
        runner.start()
        assert entered.wait(2)
        assert_blocked(controller, command)
        assert controller.transport.direction == 'stop'
        release.set()
        runner.join(2)
        assert not runner.is_alive() and errors == []
        assert_blocked(controller, command)
        assert not controller.status()['lease_active']
    finally:
        release.set()
        runner.join(2)
        controller.thread = None
        controller.close()


class FakeWorker:
    def __init__(self, **kwargs):
        self.alive = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        self.alive = False


def test_explicit_successful_restart_reopens_gate_without_restoring_lease(monkeypatch):
    controller, command = rig()
    controller.shutdown()
    assert_blocked(controller, command)
    monkeypatch.setattr(robot_control.threading, 'Thread', FakeWorker)
    try:
        controller.start()
        assert not controller.status()['lease_active']
        assert controller.status()['direction'] == 'stop'
        token = controller.acquire()['lease_token']
        assert token != command.lease_token
    finally:
        controller.close()


def test_failed_restart_does_not_reopen_shutdown_gate(monkeypatch):
    class BrokenWorker(FakeWorker):
        def start(self):
            raise RuntimeError('private failure')

    controller, command = rig()
    controller.shutdown()
    monkeypatch.setattr(robot_control.threading, 'Thread', BrokenWorker)
    try:
        with pytest.raises(ControlError, match='control_watchdog_unavailable'):
            controller.start()
        assert_blocked(controller, command)
    finally:
        controller.close()


def test_live_old_worker_cannot_reopen_gate_or_clear_stop_flag():
    controller, command = rig()
    worker = FakeWorker()
    worker.start()
    worker.join = lambda timeout: None  # Simulate a worker not exiting within join.
    controller.thread = worker
    try:
        controller.shutdown()
        controller.start()
        assert controller.thread is worker and controller.stopping.is_set()
        assert_blocked(controller, command)
    finally:
        controller.thread = None
        controller.close()
