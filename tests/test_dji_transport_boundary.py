"""Adapter-only contract checks: no SDK import, initialization or hardware."""
from types import SimpleNamespace

import pytest

from edge_hub.robot_control import ControlError, DjiEpTransport


def fake_robot(calls):
    return SimpleNamespace(chassis=SimpleNamespace(
        drive_speed=lambda **values: (calls.append(values), True)[1]))


@pytest.mark.parametrize('permission', [False, None, 0, 1, 'true', 'false', [], [True], {}])
def test_authorization_requires_literal_true_without_sdk_calls(permission):
    calls = []
    with pytest.raises(ControlError, match='on_site_ep_authorization_required') as error:
        DjiEpTransport(fake_robot(calls), model='EP', on_site_motion_authorized=permission)
    assert error.value.status == 403
    assert calls == []


@pytest.mark.parametrize('direction,ttl', [
    ('forward', True), ('forward', False), ('forward', 1.0), ('forward', 300.5),
    ('forward', '300'), ('forward', None), ('forward', 0), ('forward', 501),
    ([], 300), ({}, 300), (None, 300), ('stop', 300), ('heartbeat', 300),
    ('set_pwm', 300),
])
def test_invalid_motion_is_fixed_control_error_without_sdk_calls(direction, ttl):
    calls = []
    adapter = DjiEpTransport(fake_robot(calls), model='EP', on_site_motion_authorized=True)
    with pytest.raises(ControlError, match='unsupported_motion'):
        adapter.drive(direction, ttl)
    assert calls == []


@pytest.mark.parametrize('direction,velocity', list(DjiEpTransport.VELOCITIES.items()))
@pytest.mark.parametrize('ttl', [1, 500])
def test_fixed_directions_and_integer_ttl_boundaries_remain_supported(direction, velocity, ttl):
    calls = []
    adapter = DjiEpTransport(fake_robot(calls), model='EP', on_site_motion_authorized=True)
    adapter.drive(direction, ttl)
    assert calls == [dict(zip(('x', 'y', 'z'), velocity, strict=True), timeout=ttl / 1000)]
    assert adapter.connected is False


@pytest.mark.parametrize('result', [None, False, 0, 1, 'true', {}, []])
@pytest.mark.parametrize('action', ['drive', 'stop'])
def test_sdk_requires_explicit_true_not_unknown_return_value(result, action):
    fake = SimpleNamespace(chassis=SimpleNamespace(drive_speed=lambda **_: result))
    adapter = DjiEpTransport(fake, model='EP', on_site_motion_authorized=True)
    with pytest.raises(RuntimeError, match='sdk_.*_rejected'):
        adapter.drive('forward', 300) if action == 'drive' else adapter.stop()
