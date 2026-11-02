"""Terminal close behavior using temporary storage and controlled workers only."""
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from edge_hub import robot_control
from edge_hub.robot_control import ControlError, RobotCommand, RobotController


@pytest.mark.parametrize('operation', ['start', 'acquire', 'command', 'reset', 'stop', 'audit'])
def test_closed_controller_rejects_reuse_with_fixed_error(operation):
    controller = RobotController()
    token = controller.acquire()['lease_token']
    command = RobotCommand(lease_token=token, seq=0, issued_at_ms=1000000,
                           ttl_ms=500, direction='forward')
    controller.close()
    controller.close()  # Idempotent: never audit against an already closed connection.
    controller.shutdown()
    operations = {'start': controller.start, 'acquire': controller.acquire,
                  'command': lambda: controller.command(command), 'reset': controller.reset_software_stop,
                  'stop': controller.software_stop, 'audit': controller.audit}
    with pytest.raises(ControlError, match='^control_backend_closed$') as error:
        operations[operation]()
    assert error.value.status == 503
    assert controller.stopping.is_set()
    assert controller.status()['shutdown_requested'] is True
    assert not controller.status()['lease_active']
    assert controller.thread is None


def test_audit_failure_does_not_mark_database_closed():
    controller = RobotController()
    controller.db.execute("CREATE TRIGGER fail_stop BEFORE INSERT ON control_audit "
                          "WHEN NEW.action='stop' BEGIN SELECT RAISE(ABORT,'no'); END")
    controller.db.commit()
    try:
        with pytest.raises(ControlError, match='control_audit_unavailable'):
            controller.close()
        assert controller._closed is False
        assert controller.db.execute('SELECT 1').fetchone()[0] == 1
        assert controller.status()['state'] == 'fault'
        assert controller.status()['shutdown_requested'] is True
        controller.db.execute('DROP TRIGGER fail_stop')
        controller.db.commit()
        controller.close()
        assert controller._closed is True
    finally:
        controller.db.close()


def test_concurrent_start_waits_for_full_close_and_cannot_launch_worker(monkeypatch):
    controller = RobotController()
    entered, release, starting = threading.Event(), threading.Event(), threading.Event()
    close_errors, start_errors = [], []

    def join(timeout):
        entered.set()
        assert release.wait(2)

    controller.thread = SimpleNamespace(join=join)

    def close():
        try:
            controller.close()
        except Exception as error:  # noqa: BLE001 -- report background test failures to parent
            close_errors.append(error)

    def start():
        starting.set()
        try:
            controller.start()
        except Exception as error:  # noqa: BLE001 -- capture expected fixed ControlError and failures
            start_errors.append(error)

    closer, starter = threading.Thread(target=close), threading.Thread(target=start)

    def forbidden_worker(**kwargs):
        pytest.fail('closed controller must not construct a watchdog')

    monkeypatch.setattr(robot_control.threading, 'Thread', forbidden_worker)
    try:
        closer.start()
        assert entered.wait(2)
        starter.start()
        assert starting.wait(2)
        release.set()
        closer.join(2)
        starter.join(2)
        assert not closer.is_alive() and not starter.is_alive()
        assert close_errors == []
        assert len(start_errors) == 1 and isinstance(start_errors[0], ControlError)
        assert start_errors[0].reason == 'control_backend_closed'
        assert controller._closed is True and controller.stopping.is_set()
        with pytest.raises(sqlite3.ProgrammingError):
            controller.db.execute('SELECT 1')
    finally:
        release.set()
        closer.join(2)
        if starter.ident is not None:
            starter.join(2)
        controller.thread = None
        controller.close()
