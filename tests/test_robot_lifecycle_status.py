"""Lifecycle intent is observational, never hardware acceptance."""
from types import SimpleNamespace

import pytest

from edge_hub.robot_control import ControlError, RobotController

SCOPE = 'host shutdown intent only; not worker exit or hardware stop proof'


def test_initial_status_reports_intent_not_running_watchdog_or_hardware():
    controller = RobotController()
    try:
        status = controller.status()
        assert status['shutdown_requested'] is False
        assert status['control_lifecycle_scope'] == SCOPE
        assert controller.thread is None
        assert status['connected'] is status['hardware_acceptance'] is False
    finally:
        controller.close()


def test_shutdown_status_stays_true_after_join_and_after_software_stop():
    controller = RobotController()

    def join(timeout):
        assert controller.status()['shutdown_requested'] is True
        assert controller.status()['control_lifecycle_scope'] == SCOPE

    controller.thread = SimpleNamespace(join=join)
    try:
        controller.shutdown()
        assert controller.status()['shutdown_requested'] is True
        controller.software_stop()
        assert controller.status()['shutdown_requested'] is True
        with pytest.raises(ControlError, match='control_backend_stopping'):
            controller.acquire()
        assert controller.status()['hardware_acceptance'] is False
    finally:
        controller.thread = None
        controller.close()
