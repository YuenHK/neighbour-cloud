"""Verify stop and lease revocation precede a fake watchdog join."""
from types import SimpleNamespace

import pytest

from edge_hub.robot_control import RobotCommand, RobotController, SimulatedTransport


@pytest.mark.parametrize('stop_fails', [False, True])
@pytest.mark.parametrize('join_fails', [False, True])
def test_stop_and_durable_state_precede_join_even_on_failure(stop_fails, join_fails):
    trace = []

    class Transport(SimulatedTransport):
        def stop(self):
            trace.append('stop')
            if stop_fails:
                raise RuntimeError('private transport failure')
            super().stop()

    controller = RobotController(transport=Transport(), clock=lambda: 1000, wall_clock=lambda: 1000)
    token = controller.acquire()['lease_token']
    controller.command(RobotCommand(lease_token=token, seq=0, issued_at_ms=1000000,
                                    ttl_ms=500, direction='forward'))

    def join(timeout):
        assert timeout == 1
        assert trace == ['stop']
        assert controller.stopping.is_set()
        state = controller.status()
        assert state['shutdown_requested'] is True
        assert not state['lease_active']
        assert state['direction'] == 'stop'
        assert state['hardware_acceptance'] is False
        assert controller.motion_deadline == controller.lease_deadline == 0
        expected = 'transport_stop_failed' if stop_fails else 'backend_shutdown'
        assert controller.audit()[0]['reason'] == expected
        marker = controller.db.execute('SELECT requires_reset,fault FROM control_safety').fetchone()
        assert tuple(marker) == ((1, 1) if stop_fails else (0, 0))
        if not stop_fails:
            assert controller.transport.direction == 'stop'
        trace.append('join')
        if join_fails:
            raise RuntimeError('join failed')

    controller.thread = SimpleNamespace(join=join)
    try:
        if join_fails:
            with pytest.raises(RuntimeError, match='join failed'):
                controller.shutdown()
        else:
            controller.shutdown()
        assert trace == ['stop', 'join']  # No duplicate stop/audit after join.
        assert token not in str(controller.audit())
    finally:
        controller.thread = None
        controller.close()
