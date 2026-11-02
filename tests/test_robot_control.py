import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from edge_hub.robot_control import (
    ControlError,
    DjiEpTransport,
    RobotCommand,
    RobotController,
    SimulatedTransport,
)


@pytest.fixture
def rig():
    clock = SimpleNamespace(now=1000.)
    controller = RobotController(clock=lambda: clock.now, wall_clock=lambda: clock.now)
    yield controller, clock
    controller.close()


def command(controller, clock, token, seq=0, direction='forward', **changes):
    payload = {'lease_token': token, 'seq': seq, 'issued_at_ms': int(clock.now * 1000),
               'ttl_ms': 500, 'direction': direction, **changes}
    return controller.command(RobotCommand(**payload))


def test_single_lease_and_status_never_leaks_token(rig):
    controller, _ = rig
    token = controller.acquire()['lease_token']
    with pytest.raises(ControlError, match='in_use'):
        controller.acquire()
    assert token not in json.dumps(controller.status())
    assert token not in json.dumps(controller.audit())
    assert controller.status()['hardware_acceptance'] is False


def test_heartbeat_does_not_extend_motion_and_reconnect_never_resumes(rig):
    controller, clock = rig
    token = controller.acquire()['lease_token']
    assert command(controller, clock, token)['direction'] == 'forward'
    clock.now += .3
    command(controller, clock, token, seq=1, direction='heartbeat')
    clock.now += .201
    assert controller.status()['direction'] == 'stop'
    assert controller.status()['reason'] == 'command_timeout'
    assert not controller.status()['lease_active']
    controller.acquire()
    assert controller.status()['direction'] == 'stop'


@pytest.mark.parametrize('change', [{'seq': 0}, {'seq': 1, 'issued_at_ms': 999000},
                                   {'seq': 1, 'issued_at_ms': 1001000}])
def test_replayed_stale_or_future_command_stops_and_revokes_lease(rig, change):
    controller, clock = rig
    token = controller.acquire()['lease_token']
    command(controller, clock, token)
    with pytest.raises(ControlError, match='stale_replayed'):
        command(controller, clock, token, **change)
    assert controller.status()['direction'] == 'stop'
    assert not controller.status()['lease_active']


def test_stop_latch_requires_explicit_reset_and_new_lease(rig):
    controller, clock = rig
    token = controller.acquire()['lease_token']
    command(controller, clock, token)
    controller.software_stop()
    with pytest.raises(ControlError, match='latched'):
        controller.acquire()
    controller.reset_software_stop()
    with pytest.raises(ControlError, match='invalid_or_expired'):
        command(controller, clock, token, seq=1)
    assert controller.status()['direction'] == 'stop'


@pytest.mark.parametrize('change', [{'ttl_ms': 501}, {'ttl_ms': 99}, {'seq': True},
                                   {'direction': 'set_pwm'}, {'speed': .2}])
def test_command_contract_rejects_low_level_unknown_or_unbounded_input(change):
    with pytest.raises(ValidationError):
        RobotCommand(**({'lease_token': 'x' * 32, 'seq': 0, 'issued_at_ms': 1000000,
                         'ttl_ms': 500, 'direction': 'forward'} | change))


def test_audit_persists_without_storing_lease_secrets(tmp_path):
    path = tmp_path / 'control.sqlite3'
    first = RobotController(path)
    token = first.acquire()['lease_token']
    first.close()
    second = RobotController(path)
    try:
        assert any(row['action'] == 'lease_acquired' for row in second.audit())
        assert token not in json.dumps(second.audit())
        assert not second.status()['lease_active']
    finally:
        second.close()


def test_transport_failure_revokes_lease_and_latches_stop():
    class BrokenTransport(SimulatedTransport):
        def drive(self, *_):
            raise RuntimeError('private SDK internals')

    controller = RobotController(transport=BrokenTransport(), clock=lambda: 1000, wall_clock=lambda: 1000)
    try:
        token = controller.acquire()['lease_token']
        with pytest.raises(ControlError, match='transport_command_failed'):
            command(controller, SimpleNamespace(now=1000), token)
        assert controller.status()['software_stop_latched']
        assert not controller.status()['lease_active']
    finally:
        controller.close()


def test_audit_failure_cannot_leave_a_moving_command_or_a_valid_lease():
    controller = RobotController(clock=lambda: 1000, wall_clock=lambda: 1000)
    token = controller.acquire()['lease_token']
    controller.db.close()
    with pytest.raises(ControlError, match='control_audit_unavailable'):
        command(controller, SimpleNamespace(now=1000), token)
    assert controller.transport.direction == 'stop'
    assert controller.status()['state'] == 'fault'
    assert controller.status()['software_stop_latched']
    assert not controller.status()['lease_active']


def test_sdk_adapter_is_ep_only_requires_on_site_authority_and_never_initializes_robot():
    calls = []
    fake = SimpleNamespace(chassis=SimpleNamespace(
        drive_speed=lambda **values: (calls.append(values), True)[1]))
    for model, permission in [('S1', True), ('EP', False)]:
        with pytest.raises(ControlError):
            DjiEpTransport(fake, model=model, on_site_motion_authorized=permission)
    assert calls == []
    adapter = DjiEpTransport(fake, model='EP', on_site_motion_authorized=True)
    adapter.drive('forward', 300)
    adapter.stop()
    assert calls == [{'x': .15, 'y': 0, 'z': 0, 'timeout': .3},
                     {'x': 0, 'y': 0, 'z': 0, 'timeout': .1}]


def test_software_stop_survives_clean_restart_until_explicit_reset(tmp_path):
    path = tmp_path / 'control.sqlite3'
    first = RobotController(path)
    first.software_stop()
    first.close()
    second = RobotController(path)
    try:
        assert second.status()['software_stop_latched']
        assert second.status()['direction'] == 'stop'
        with pytest.raises(ControlError, match='latched'):
            second.acquire()
        second.reset_software_stop()
    finally:
        second.close()
    third = RobotController(path)
    try:
        assert not third.status()['software_stop_latched']
        assert not third.status()['lease_active']
    finally:
        third.close()


def test_unclean_lease_restart_requires_confirmation_and_does_not_restore_secret(tmp_path):
    path = tmp_path / 'control.sqlite3'
    first = RobotController(path)
    token = first.acquire()['lease_token']
    first.db.close()  # Simulated abrupt process loss, bypass normal shutdown.
    second = RobotController(path)
    try:
        status = second.status()
        assert status['software_stop_latched'] and not status['lease_active']
        assert status['direction'] == 'stop'
        assert token not in json.dumps(second.audit())
        with pytest.raises(ControlError):
            second.acquire()
    finally:
        second.close()


def test_persisted_transport_stop_fault_is_not_cleared_by_restart_or_reset(tmp_path):
    class BrokenStop(SimulatedTransport):
        def stop(self):
            raise RuntimeError('private details')

    path = tmp_path / 'control.sqlite3'
    first = RobotController(path, transport=BrokenStop())
    first.software_stop()
    first.close()
    second = RobotController(path)
    try:
        assert second.status()['state'] == 'fault'
        with pytest.raises(ControlError, match='on_site'):
            second.reset_software_stop()
    finally:
        second.close()


def test_clean_idle_restart_does_not_create_lease_or_require_reset(tmp_path):
    path = tmp_path / 'control.sqlite3'
    first = RobotController(path)
    first.acquire()
    first.close()
    second = RobotController(path)
    try:
        assert not second.status()['software_stop_latched']
        assert not second.status()['lease_active']
        assert second.status()['direction'] == 'stop'
    finally:
        second.close()


def test_legacy_audit_without_safety_marker_requires_confirmation(tmp_path):
    import sqlite3

    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as database:
        database.execute('CREATE TABLE control_audit '
                         '(id INTEGER PRIMARY KEY,at_ms INTEGER,action TEXT,reason TEXT)')
        database.execute("INSERT INTO control_audit VALUES (1,1,'stop','backend_shutdown')")
    controller = RobotController(path)
    try:
        assert controller.status()['software_stop_latched']
        controller.reset_software_stop()
        assert controller.audit()[-1]['reason'] == 'backend_shutdown'
    finally:
        controller.close()


def test_failed_reset_transaction_cannot_clear_durable_stop_marker(tmp_path):
    path = tmp_path / 'control.sqlite3'
    first = RobotController(path)
    first.software_stop()
    first.db.execute("CREATE TRIGGER fail_reset BEFORE INSERT ON control_audit "
                     "WHEN NEW.action='reset_software_stop' BEGIN SELECT RAISE(ABORT,'no'); END")
    first.db.commit()
    with pytest.raises(ControlError, match='audit_unavailable'):
        first.reset_software_stop()
    first.db.close()  # Abrupt loss after failed persistence; do not run normal shutdown.
    second = RobotController(path)
    try:
        assert second.status()['software_stop_latched']
        assert not any(row['action'] == 'reset_software_stop' for row in second.audit())
    finally:
        second.close()
