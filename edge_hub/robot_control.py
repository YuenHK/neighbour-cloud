"""Operator-only, stop-first robot arbitration. The API defaults to simulation.

Host watchdogs and SDK timeouts do NOT prove physical stop on PC/network failure.
DJI EP transport consumes an explicitly initialized SDK object; never auto-connect.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal['forward', 'backward', 'left', 'right', 'turn_left', 'turn_right', 'stop', 'heartbeat']


class RobotCommand(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    lease_token: str = Field(min_length=20, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    seq: int = Field(ge=0, le=2**31 - 1)
    issued_at_ms: int = Field(ge=0)
    ttl_ms: int = Field(ge=100, le=500)
    direction: Direction


class ControlError(Exception):
    def __init__(self, reason, status=409):
        self.reason, self.status = reason, status
        super().__init__(reason)


def _read_safety_marker(database):
    rows = database.execute('SELECT id,requires_reset,fault FROM control_safety LIMIT 2').fetchall()
    if (len(rows) != 1 or any(type(value) is not int for value in rows[0])
            or rows[0]['id'] != 1 or any(rows[0][name] not in (0, 1) for name in ('requires_reset', 'fault'))):
        raise sqlite3.IntegrityError('invalid control safety marker')
    return rows[0]


class SimulatedTransport:
    mode = 'simulation'
    connected = False

    def __init__(self):
        self.direction = 'stop'

    def drive(self, direction, ttl_ms):
        self.direction = direction

    def stop(self):
        self.direction = 'stop'


class DjiEpTransport:
    """Maps fixed low-speed directions to DJI's chassis.drive_speed API.

    No connection, camera, microphone, gimbal or blaster initialization here.
    Requires on-site authorization and an already initialized EP SDK object.
    S1 is deliberately unsupported rather than silently treated as EP.
    DJI's timeout is implemented by a host threading.Timer, not proof of an
    independent robot watchdog. Never certify PC/network-failure stop from it.
    """
    mode = 'dji-ep-sdk-unverified'
    connected = False  # Supplying an SDK object is NOT proof of a verified physical link.
    VELOCITIES: ClassVar[dict[str, tuple[float, float, float]]] = {'forward': (.15, 0, 0), 'backward': (-.15, 0, 0),
                  'left': (0, -.15, 0), 'right': (0, .15, 0),
                  'turn_left': (0, 0, -15), 'turn_right': (0, 0, 15)}

    def __init__(self, sdk_robot, *, model, on_site_motion_authorized=False):
        if type(model) is not str or model != 'EP' or on_site_motion_authorized is not True:
            raise ControlError('on_site_ep_authorization_required', 403)
        self.robot = sdk_robot

    def drive(self, direction, ttl_ms):
        if (type(direction) is not str or direction not in self.VELOCITIES
                or type(ttl_ms) is not int or not 1 <= ttl_ms <= 500):
            raise ControlError('unsupported_motion')
        x, y, z = self.VELOCITIES[direction]
        if self.robot.chassis.drive_speed(x=x, y=y, z=z, timeout=ttl_ms / 1000) is not True:
            raise RuntimeError('sdk_motion_rejected')

    def stop(self):
        if self.robot.chassis.drive_speed(x=0, y=0, z=0, timeout=.1) is not True:
            raise RuntimeError('sdk_stop_rejected')


class RobotController:
    LEASE_MS = 2000

    def __init__(self, database=':memory:', *, transport=None,
                 clock=time.monotonic, wall_clock=time.time):
        if str(database) != ':memory:':
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(database), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute('CREATE TABLE IF NOT EXISTS control_audit '
                            '(id INTEGER PRIMARY KEY, at_ms INTEGER NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL)')
            marker_entry = self.db.execute(
                "SELECT type FROM sqlite_master WHERE name='control_safety'").fetchone()
            marker_existed = marker_entry is not None
            if marker_existed and marker_entry[0] != 'table':
                raise sqlite3.IntegrityError('invalid control safety table')
            self.db.execute('CREATE TABLE IF NOT EXISTS control_safety '
                            '(id INTEGER PRIMARY KEY CHECK(id=1), '
                            'requires_reset INTEGER NOT NULL CHECK(requires_reset IN (0,1)), '
                            'fault INTEGER NOT NULL CHECK(fault IN (0,1)))')
            # Only a genuinely legacy absent table may receive a synthesized marker.
            if not marker_existed:
                legacy_history = bool(self.db.execute('SELECT 1 FROM control_audit LIMIT 1').fetchone())
                self.db.execute('INSERT INTO control_safety VALUES (1,?,0)', (int(legacy_history),))
            saved = _read_safety_marker(self.db)
            self.db.commit()
        except sqlite3.Error:
            self.db.close()
            raise ControlError('control_safety_storage_invalid', 503) from None
        self.transport = transport or SimulatedTransport()
        self.clock, self.wall_clock = clock, wall_clock
        self.lock = threading.RLock()
        self.lifecycle_lock = threading.RLock()
        self._shutdown_requested = False
        self._closed = False
        self.lease = None
        self.lease_deadline = self.motion_deadline = 0.
        self.sequence = -1
        self.direction = 'stop'
        self.state = 'fault' if saved['fault'] else 'safe_stop' if saved['requires_reset'] else 'idle'
        self.reason = ('persisted_fault_requires_on_site_check' if saved['fault'] else
                       'restart_requires_stationary_confirmation' if saved['requires_reset'] else
                       'not_connected_to_hardware')
        self.stop_latched = bool(saved['requires_reset'] or saved['fault'])
        self.stopping = threading.Event()
        self.thread = None

    def _audit(self, action, reason=''):
        try:
            self.db.execute('INSERT INTO control_audit(at_ms,action,reason) VALUES (?,?,?)',
                            (int(self.wall_clock() * 1000), action, reason))
            # Persist only safety flags, NEVER the lease secret or a resumable direction.
            # A live lease is an unclean-restart marker until a successful stop is recorded.
            expected = (int(self.stop_latched or bool(self.lease) or self.direction != 'stop'),
                        int(self.state == 'fault'))
            updated = self.db.execute('UPDATE control_safety SET requires_reset=?,fault=? WHERE id=1', expected)
            if updated.rowcount != 1:
                raise sqlite3.IntegrityError('control safety marker was not updated')
            saved = _read_safety_marker(self.db)
            if (saved['requires_reset'], saved['fault']) != expected:
                raise sqlite3.IntegrityError('control safety marker did not preserve flags')
            self.db.commit()
        except sqlite3.Error:
            try:
                self.db.rollback()
            except sqlite3.Error:
                pass  # Closed/unavailable storage cannot acknowledge a safety transition.
            self.state, self.reason = 'fault', 'audit_failure'
            self.stop_latched, self.lease, self.direction = True, None, 'stop'
            self.stopping.set()
            try:
                self.transport.stop()
            except Exception:  # noqa: BLE001 -- audit failure must remain latched even if stop fails
                self.reason = 'audit_and_stop_failed'
            raise ControlError('control_audit_unavailable', 503) from None

    def _stop(self, reason, *, latch=False):
        prior_fault = self.state == 'fault'
        fault_reason = self.reason
        try:
            self.transport.stop()
            self.state = 'fault' if prior_fault else 'safe_stop'
            if prior_fault:
                reason, latch = fault_reason, True
        except Exception:  # noqa: BLE001 -- any SDK failure must stop; never leak driver internals
            self.state = 'fault'
            reason = 'transport_stop_failed'
            latch = True
        self.direction = 'stop'
        self.lease = None
        self.motion_deadline = self.lease_deadline = 0.
        self.stop_latched = self.stop_latched or latch
        self.reason = reason
        self._audit('stop', reason)

    def tick(self):
        with self.lock:
            now = self.clock()
            if self.direction != 'stop' and now >= self.motion_deadline:
                self._stop('command_timeout')
            elif self.lease and now >= self.lease_deadline:
                self._stop('lease_expired')

    def acquire(self):
        with self.lock:
            self._require_accepting_commands()
            self.tick()
            if self.stop_latched or self.state == 'fault':
                raise ControlError('software_stop_latched', 423)
            if self.lease:
                raise ControlError('control_lease_in_use')
            self.lease = secrets.token_urlsafe(32)
            self.sequence = -1
            self.lease_deadline = self.clock() + self.LEASE_MS / 1000
            self._audit('lease_acquired')
            return {'lease_token': self.lease, 'expires_in_ms': self.LEASE_MS,
                    'server_time_ms': int(self.wall_clock() * 1000), 'mode': self.transport.mode}

    def command(self, command: RobotCommand):
        with self.lock:
            self._require_accepting_commands()
            self.tick()
            if not self.lease or not secrets.compare_digest(command.lease_token, self.lease):
                raise ControlError('invalid_or_expired_lease', 403)
            age_ms = int(self.wall_clock() * 1000) - command.issued_at_ms
            if command.seq <= self.sequence or age_ms < -100 or age_ms >= command.ttl_ms:
                self._stop('stale_replayed_or_future_command')
                raise ControlError('stale_replayed_or_future_command')
            self.sequence = command.seq
            if command.direction == 'stop':
                self._stop('operator_release')
            else:
                self.lease_deadline = self.clock() + self.LEASE_MS / 1000
                if command.direction != 'heartbeat':
                    try:
                        remaining_ms = min(command.ttl_ms, command.ttl_ms - max(0, age_ms))
                        deadline = self.clock() + remaining_ms / 1000
                        self.transport.drive(command.direction, remaining_ms)
                    except Exception:  # noqa: BLE001 -- hardware adapter failures fail closed
                        self._stop('transport_command_failed', latch=True)
                        raise ControlError('transport_command_failed', 503) from None
                    self.direction, self.state, self.reason = command.direction, 'manual', 'operator_command'
                    self.motion_deadline = deadline
                # Heartbeats renew ownership only; they NEVER extend motion.
                self._audit(command.direction)
            return self.status()

    def software_stop(self):
        with self.lock:
            self._require_open()
            self._stop('operator_software_stop', latch=True)
            return self.status()

    def reset_software_stop(self):
        with self.lock:
            self._require_accepting_commands()
            self.tick()  # Expiry must stop first; a stop fault cannot be reset below.
            if self.state == 'fault':
                raise ControlError('transport_fault_requires_on_site_check', 423)
            if self.direction != 'stop' or self.lease is not None:
                raise ControlError('control_must_be_stopped_before_reset', 423)
            self.stop_latched = False
            self.state, self.reason = 'idle', 'operator_checked_stationary'
            self.lease = None
            self._audit('reset_software_stop')
            return self.status()

    def status(self):
        with self.lock:
            self.tick()
            return {'mode': self.transport.mode, 'connected': self.transport.connected,
                    'state': self.state, 'direction': self.direction, 'reason': self.reason,
                    'lease_active': bool(self.lease), 'software_stop_latched': self.stop_latched,
                    'shutdown_requested': self._shutdown_requested,
                    'control_lifecycle_scope': 'host shutdown intent only; not worker exit or hardware stop proof',
                    'host_command_timeout_ms': 500, 'hardware_watchdog_verified': False,
                    'hardware_acceptance': False, 'physical_emergency_stop': 'not_verified',
                    'server_time_ms': int(self.wall_clock() * 1000)}

    def audit(self, limit=100, *, before_id=None):
        with self.lock:
            self._require_open()
            if type(limit) is not int or not 1 <= limit <= 200:
                raise ControlError('invalid_audit_limit', 422)
            if before_id is not None and (type(before_id) is not int or not 1 <= before_id <= 2**63 - 1):
                raise ControlError('invalid_audit_cursor', 422)
            if before_id is None:
                rows = self.db.execute('SELECT * FROM control_audit ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
            else:
                rows = self.db.execute('SELECT * FROM control_audit WHERE id < ? ORDER BY id DESC LIMIT ?',
                                       (before_id, limit)).fetchall()
            return [dict(row) for row in rows]

    def _require_open(self):
        if self._closed:
            raise ControlError('control_backend_closed', 503)

    def _require_accepting_commands(self):
        self._require_open()
        if self._shutdown_requested:
            raise ControlError('control_backend_stopping', 503)

    def start(self):
        with self.lifecycle_lock, self.lock:
            self._require_open()
            if self.thread and self.thread.is_alive():
                return
            self.stopping.clear()

            def watch():
                while not self.stopping.wait(.05):
                    try:
                        self.tick()
                    except Exception:  # noqa: BLE001 -- audit/SDK failures must latch the watchdog
                        # Persistent audit failure must not leave a motion alive.
                        with self.lock:
                            self.state, self.reason = 'fault', 'watchdog_failure'
                            self.stop_latched, self.lease, self.direction = True, None, 'stop'
                            self.motion_deadline = self.lease_deadline = 0.
                            self.stopping.set()
                            try:
                                self.transport.stop()
                            except Exception:  # noqa: BLE001 -- retain latched fault if stop also fails
                                self.reason = 'watchdog_stop_failed'
                            try:
                                self._audit('watchdog_failure', self.reason)
                            except ControlError:
                                pass  # Audit failure already latched fault and attempted fallback stop.

            try:
                self.thread = threading.Thread(target=watch, daemon=True)
                self.thread.start()
                self._shutdown_requested = False
            except Exception:  # noqa: BLE001 -- failed watchdog launch must revoke motion authority
                self.stopping.set()
                if self.thread is not None and not self.thread.is_alive():
                    self.thread = None  # An unstarted thread cannot be joined during cleanup.
                self.state, self.reason = 'fault', 'watchdog_start_failed'
                self._stop('watchdog_start_failed', latch=True)
                raise ControlError('control_watchdog_unavailable', 503) from None

    def shutdown(self):
        with self.lifecycle_lock:
            with self.lock:
                if self._closed:
                    return
                self._shutdown_requested = True
                self.stopping.set()
                # Do not leave motion awaiting join after asking its watchdog to exit.
                self._stop('backend_shutdown')
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=1)

    def close(self):
        with self.lifecycle_lock:
            if self._closed:
                return
            self.shutdown()
            with self.lock:
                self.db.close()
                self._closed = True
