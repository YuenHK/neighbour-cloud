import sqlite3
from contextlib import closing

import pytest

from edge_hub.robot_control import ControlError
from edge_hub.stop_fault_recovery import retain_stop_after_historical_fault


@pytest.fixture
def recovery(tmp_path):
    path = tmp_path / 'control.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        db.executescript('''
            CREATE TABLE control_safety(id INTEGER PRIMARY KEY,requires_reset INTEGER,fault INTEGER);
            CREATE TABLE control_audit(id INTEGER PRIMARY KEY,at_ms INTEGER,action TEXT,reason TEXT);
            INSERT INTO control_safety VALUES(1,1,1);
            INSERT INTO control_audit VALUES(189,1,'stop','transport_stop_failed');
        ''')
        db.commit()
    state = {'sn': 'SYNTHETIC', 'connection': 'connected', 'prepared_idle': False,
             'prepare_attempted': False, 'movement_enabled': False, 'safety_hold': True,
             'chassis_motion_allowed': True, 'chassis_status_age_ms': 20,
             'control': {'persisted_only': True, 'state': 'fault', 'lease_active': False,
                         'direction': 'stop', 'software_stop_latched': True}}
    return path, state


def recover(path, state, **extra):
    return retain_stop_after_historical_fault(path, state, expected_sn='SYNTHETIC',
        expected_audit_id=189, confirmed_power_cycle=True, **extra)


def test_recovery_keeps_stop_lock_and_original_fault_row(recovery):
    path, state = recovery
    result = recover(path, state)
    assert result['requires_stationary_reset'] and not result['hardware_commands_sent']
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT requires_reset,fault FROM control_safety').fetchone() == (1, 0)
        assert db.execute('SELECT * FROM control_audit WHERE id=189').fetchone() == (189, 1, 'stop', 'transport_stop_failed')
        assert db.execute('SELECT action FROM control_audit WHERE id=190').fetchone()[0] == 'historical_stop_fault_reclassified'
    with pytest.raises(ControlError):
        recover(path, state)


@pytest.mark.parametrize('key,value', [
    ('sn', 'OTHER'), ('connection', 'not_connected'), ('prepared_idle', True),
    ('prepare_attempted', True), ('movement_enabled', True), ('safety_hold', False),
    ('chassis_motion_allowed', False), ('chassis_status_age_ms', 500), ('status_busy', True),
    ('status_age_ms', 500),
])
def test_wrong_or_stale_live_state_cannot_change_marker(recovery, key, value):
    path, state = recovery
    state[key] = value
    with pytest.raises(ControlError):
        recover(path, state)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT requires_reset,fault FROM control_safety').fetchone() == (1, 1)
        assert db.execute('SELECT COUNT(*) FROM control_audit').fetchone()[0] == 1


@pytest.mark.parametrize('key,value', [('persisted_only', False), ('lease_active', True), ('direction', 'forward')])
def test_active_controller_never_reclassified(recovery, key, value):
    path, state = recovery
    state['control'][key] = value
    with pytest.raises(ControlError):
        recover(path, state)


def test_other_fault_or_new_audit_is_not_eligible(recovery):
    path, state = recovery
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE control_audit SET reason='motor_work_mode_unconfirmed'")
        db.commit()
    with pytest.raises(ControlError):
        recover(path, state)


def test_failed_audit_insert_rolls_back_reclassification(recovery):
    path, state = recovery
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TRIGGER deny_audit BEFORE INSERT ON control_audit BEGIN SELECT RAISE(ABORT, 'denied'); END")
        db.commit()
    with pytest.raises(ControlError):
        recover(path, state)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT requires_reset,fault FROM control_safety').fetchone() == (1, 1)


def test_freshness_is_rechecked_after_transaction_lock(recovery):
    path, state = recovery
    times = iter((0., 1.))
    with pytest.raises(ControlError):
        recover(path, state, clock=lambda: next(times))
