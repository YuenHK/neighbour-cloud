import time
from types import SimpleNamespace

import pytest

from edge_hub.robot_control import ControlError
from ep_runtime.infrared_warning import InfraredWarning


def fake():
    calls = []
    def fire(**kw):
        assert kw == {'fire_type': 'ir', 'times': 1}
        calls.append(('ir', kw))
        return True
    robot = SimpleNamespace(blaster=SimpleNamespace(fire=fire,
        set_led=lambda **kw: calls.append(('led', kw)) or True),
        play_sound=lambda **kw: calls.append(('sound', kw)) or SimpleNamespace(has_succeeded=True))
    return robot, calls


def test_release_fences_late_start_and_only_explicit_ir_is_sent():
    robot, calls = fake()
    warning = InfraredWarning()
    warning.update(robot, 'press-001', False)
    with pytest.raises(ControlError):
        warning.update(robot, 'press-001', True)
    assert not calls
    warning.update(robot, 'press-002', True)
    time.sleep(.02)
    warning.update(robot, 'press-002', False)
    warning.thread.join(1)
    assert len([c for c in calls if c[0] == 'ir']) == 1
    assert calls[-1] == ('led', {'brightness': 0, 'effect': 'off'})
    assert warning.state == 'stopped'
    with pytest.raises(ControlError):
        warning.update(robot, 'press-002', True)


def test_heartbeat_has_no_total_duration_limit_but_loss_stops():
    now = [0]
    robot, calls = fake()
    warning = InfraredWarning(clock=lambda: now[0])
    warning.update(robot, 'press-003', True)
    now[0] = 1
    warning.update(robot, 'press-003', True)
    assert warning.deadline == 2.5
    now[0] = 1000
    warning.thread.join(1)
    assert not warning.thread.is_alive()
    assert calls[-1] == ('led', {'brightness': 0, 'effect': 'off'})
