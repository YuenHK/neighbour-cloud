"""Explicit recovery of a historical stop-transport fault, retaining stop lock.

This does not enable hardware or reset a controller. Unknown/current faults are
never eligible. The caller must have operator authority and a fresh GET snapshot.
"""
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from edge_hub.robot_control import ControlError, _read_safety_marker


def retain_stop_after_historical_fault(
    database: Path, state: dict, *, expected_sn: str, expected_audit_id: int,
    confirmed_power_cycle: bool, clock=time.monotonic,
):
    started = clock()
    control = state.get('control') or {}
    age = state.get('chassis_status_age_ms')
    cache_age = state.get('status_age_ms', 0)
    if (confirmed_power_cycle is not True or type(expected_audit_id) is not int or expected_audit_id < 1
            or not expected_sn or state.get('sn') != expected_sn or state.get('connection') != 'connected'
            or state.get('prepared_idle') is not False or state.get('prepare_attempted') is not False
            or state.get('movement_enabled') is not False or state.get('safety_hold') is not True
            or state.get('chassis_motion_allowed') is not True or state.get('status_busy')
            or control.get('persisted_only') is not True or control.get('state') != 'fault'
            or control.get('lease_active') is not False or control.get('direction') != 'stop'
            or control.get('software_stop_latched') is not True
            or type(age) is not int or type(cache_age) is not int
            or not 0 <= age + cache_age < 500):
        raise ControlError('Historical recovery requires a verified, fresh, unprepared session.', 423)
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=rw', uri=True, timeout=.2)) as db:
            db.row_factory = sqlite3.Row
            with db:
                db.execute('BEGIN IMMEDIATE')
                if age + cache_age + (clock() - started) * 1000 >= 500:
                    raise ControlError('Recovery observation expired; no change made.', 423)
                marker = _read_safety_marker(db)
                latest = db.execute('SELECT id,action,reason FROM control_audit ORDER BY id DESC LIMIT 1').fetchone()
                if ((marker['requires_reset'], marker['fault']) != (1, 1) or latest is None
                        or latest['id'] != expected_audit_id or latest['action'] != 'stop'
                        or latest['reason'] != 'transport_stop_failed'):
                    raise ControlError('The original historical fault no longer matches; no change made.', 423)
                changed = db.execute('UPDATE control_safety SET fault=0 WHERE id=1 AND requires_reset=1 AND fault=1')
                if changed.rowcount != 1:
                    raise sqlite3.IntegrityError('recovery marker update failed')
                db.execute('INSERT INTO control_audit(at_ms,action,reason) VALUES (?,?,?)',
                    (int(time.time() * 1000), 'historical_stop_fault_reclassified',
                     f'operator_requested;original_fault_id={expected_audit_id};stationary_reset_required'))
                saved = _read_safety_marker(db)
                if (saved['requires_reset'], saved['fault']) != (1, 0):
                    raise sqlite3.IntegrityError('stop lock must remain')
        return {'fault_reclassified': True, 'requires_stationary_reset': True,
                'original_fault_audit_id': expected_audit_id, 'hardware_commands_sent': False}
    except sqlite3.Error:
        raise ControlError('Recovery storage unavailable; no hardware operation attempted.', 503) from None
