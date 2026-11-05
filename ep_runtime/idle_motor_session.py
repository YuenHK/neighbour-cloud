"""Experimental stage six; operator confirms rest before releasing wheel control."""
import secrets
import threading
import time

from edge_hub.robot_control import ControlError
from ep_runtime.body_snapshot import subscribe_body_snapshots
from ep_runtime.console_session import LiveTransport
from ep_runtime.esc_snapshot import EscSnapshot, subscribe_snapshot_esc
from ep_runtime.motor_trace import MotorTrace, sdk_counters
from ep_runtime.release_evidence import ReleaseEvidence
from ep_runtime.rest_evidence import RestEvidence
from ep_runtime.short_press_session import ReleaseCheckEpSession


class IdleMotorTransport(LiveTransport):
    def __init__(self, session):
        super().__init__(session.robot, model='EP', on_site_motion_authorized=True)
        self.session = session

    def stop(self):
        # A previously stopped and explicitly released chassis must remain idle
        # on disconnect. A zero wheel target could engage its motors again.
        if self.session.motor_state == 'released_reply':
            return
        super().stop()
        self.session.record_stop()


class IdleMotorEpSession(ReleaseCheckEpSession):
    STAGE = 6
    # Body-frame evidence is mandatory; motor-count history remains diagnostic.
    # An accepted engineering window is not a physical stationary certification.
    REST_RPM_MAX = RestEvidence.RPM_LIMIT
    REST_SECONDS = RestEvidence.WINDOW

    def __init__(self, *args, **kwargs):
        self.motor_state = 'unknown'
        self.release_ack = None
        self.release_at = None
        self.motor_mode_diagnostics = []
        self.release_evidence = ReleaseEvidence()
        self.motor_stop_id = None
        self.motor_press = None
        self.motor_attempted = False
        self.esc_lock = threading.Lock()
        self.rest_evidence = RestEvidence()
        self.esc_atomic_snapshot = False
        self.esc_last_payload = None
        self.esc_duplicates = 0
        self.esc_stop_at = 0.
        self.esc_stamp = None
        self.esc_at = None
        self.esc_received = 0
        self.esc_invalid = 0
        self.esc_speeds = None
        self.esc_angles = None
        self.esc_reason = 'waiting_for_samples'
        super().__init__(*args, **kwargs)
        self.motor_trace = MotorTrace(self.root)

    def persist_motor_evidence(self, evidence, *, before_command=False):
        try:
            self.motor_trace.append(evidence, sn=self.sn, device_id=self.device_id, firmware=self.version)
            evidence['diagnostic_persisted'] = True
        except OSError:
            evidence['diagnostic_persisted'] = False
            if before_command:
                raise ControlError('本機電機診斷紀錄無法寫入；未發出本次電機指令。', 503) from None
            self.motor_failure(reason='motor_transition_record_unavailable')

    def record_stop(self):
        with self.esc_lock:
            self.motor_stop_id = secrets.token_hex(16)
            self.esc_stop_at = time.monotonic()
            self.release_evidence = ReleaseEvidence(self.esc_stop_at)
            self.release_ack = self.release_at = None
            self.rest_evidence = RestEvidence()
            self.rest_evidence.reason = 'waiting_after_stop'
            self.esc_at = None
            self.esc_angles = None
            self.esc_reason = 'waiting_after_stop'

    def receive_body(self, frame):
        with self.esc_lock:
            self.release_evidence.add_body(frame, time.monotonic())

    def receive_esc(self, values):
        now = time.monotonic()
        atomic = isinstance(values, EscSnapshot)
        observed = values.decoded_at if atomic else now
        values = values.values if atomic else values
        with self.esc_lock:
            self.esc_received += 1
            self.esc_atomic_snapshot = atomic
            if not atomic:
                self.rest_evidence.invalidate('unverified_snapshot')
                self.release_evidence.invalidate_wheels('unverified_snapshot')
                self.esc_at = None
                self.esc_reason = 'unverified_snapshot'
                return
            if type(observed) not in (int, float) or not 0 <= now - observed < .25:
                self.rest_evidence.invalidate('delayed_callback')
                self.release_evidence.invalidate_wheels('delayed_callback')
                self.esc_at = None
                self.esc_reason = 'delayed_callback'
                return
            if observed < self.esc_stop_at:
                if self.esc_at is None:
                    self.esc_reason = 'waiting_after_stop'
                return  # a queued pre-ACK callback is not post-stop evidence
            valid = (isinstance(values, (list, tuple)) and len(values) == 4
                     and all(isinstance(part, (list, tuple)) and len(part) == 4 for part in values))
            if valid:
                speeds, angles, stamps, _ = values
                valid = (all(type(v) is int and -8192 <= v <= 8191 for v in speeds)
                         and all(type(v) is int and 0 <= v <= 32767 for v in angles)
                         and all(type(v) is int and 0 <= v <= 0xffffffff for v in stamps))
            if not valid:
                self.esc_invalid += 1
                self.esc_reason = 'invalid_sample'
                self.esc_speeds = None
                self.esc_angles = None
                self.rest_evidence.invalidate('invalid_sample')
                self.release_evidence.invalidate_wheels('invalid_sample')
                self.esc_at = None
                return
            payload = tuple(tuple(part) for part in values)
            if payload == self.esc_last_payload:
                self.esc_duplicates += 1
                return  # native DDS can execute twice; never refresh sample age
            advancing = (self.esc_stamp is None or all(
                0 < (new - old) % 2**32 < 2**31 for new, old in zip(stamps, self.esc_stamp, strict=True)))
            gap = self.esc_at is not None and observed - self.esc_at > .25
            self.esc_speeds = tuple(speeds)
            self.esc_angles = tuple(angles)
            if not advancing or gap:
                reason = 'sequence_not_advancing' if not advancing else 'sample_gap'
                self.rest_evidence.invalidate(reason)
                self.release_evidence.invalidate_wheels(reason)
            self.esc_stamp = tuple(stamps)
            self.esc_last_payload = payload
            self.esc_at = observed
            if advancing:
                self.release_evidence.add_wheels(observed, speeds, angles)
                self.rest_evidence.add(observed, speeds, angles)
                self.rest_evidence.evaluate()
            self.esc_reason = self.rest_evidence.reason

    def esc_diagnostics(self):
        with self.esc_lock:
            age = time.monotonic() - self.esc_at if self.esc_at is not None else None
            return {'received': self.esc_received, 'invalid': self.esc_invalid,
                    'speeds_rpm': self.esc_speeds, 'sequences': self.esc_stamp,
                    'angles_raw': self.esc_angles,
                    'atomic_snapshot': self.esc_atomic_snapshot,
                    'duplicate_callbacks': self.esc_duplicates,
                    'rest_rpm_ceiling': self.REST_RPM_MAX, 'rest_required_ms': 2000,
                    'isolated_rpm_absolute_max': RestEvidence.MAX_ISOLATED_RPM,
                    'sample_age_ms': int(age * 1000) if age is not None else None,
                    **self.release_evidence.metrics,
                    'encoder_comparator': {**self.rest_evidence.metrics,
                                           'reason': self.rest_evidence.reason,
                                           'first_block': self.rest_evidence.blocked_evidence},
                    'encoder_reference_locked': self.rest_evidence.anchor is not None,
                    'body_reference_locked': self.release_evidence.body_reference is not None,
                    'first_body_signal_anomaly': self.release_evidence.first_anomaly,
                    'first_block_evidence': self.release_evidence.first_block,
                    'first_signal_anomaly': self.rest_evidence.first_signal_anomaly,
                    'signal_recovery_pending': self.rest_evidence.signal_recovery_pending,
                    'signal_recoveries': self.rest_evidence.signal_recoveries,
                    'reason': 'stale_sample' if age is not None and age >= .25 else self.esc_reason
                        if self.esc_reason in {'unverified_snapshot', 'delayed_callback', 'invalid_sample',
                                               'sequence_not_advancing', 'waiting_after_stop'}
                        else self.release_evidence.reason}

    def wheels_at_rest(self):
        with self.esc_lock:
            return bool(self.esc_atomic_snapshot and self.esc_at is not None
                        and time.monotonic() - self.esc_at < .25
                        and self.release_evidence.evaluate(time.monotonic()))

    def prepare_control(self):
        result = super().prepare_control()
        # Only this restricted experiment uses the adapter and extra telemetry.
        self.control.transport = IdleMotorTransport(self)
        self.motor_state = 'holding_zero'
        self.record_stop()
        robot = self.robot
        if subscribe_snapshot_esc(robot, lambda values: self.receive_esc(values)
                                  if self.robot is robot else None) is not True:
            self.motor_failure()
        if subscribe_body_snapshots(robot, lambda frame: self.receive_body(frame)
                                    if self.robot is robot else None) is not True:
            self.motor_failure()
        return result

    def motor_failure(self, reason='motor_work_mode_unconfirmed'):
        self.motor_state = 'unknown'
        if self.control:
            with self.control.lock:
                self.control.state = 'fault'
                self.control.reason = reason
                self.control.software_stop()
        raise ControlError('電機模式未確認，請結束並在現場關機；不會重試或移動。', 503)

    def set_motor(self, enabled):
        # DJI supplies this protocol class; mode meaning is corroborated by the
        # ROS author's engage(). Do not use SDK _set_mode: it drops its argument.
        from robomaster import protocol
        proto = protocol.ProtoChassisSetWorkMode()
        proto._mode = 1 if enabled else 0
        message = protocol.Msg(self.robot.client.hostbyte, self.robot.chassis._host, proto)
        started = time.monotonic()
        evidence = {'stage': 'engage_mode' if enabled else 'release_mode',
                    'requested_mode': int(enabled), 'ack_timeout_ms': 500,
                    'started_at_ms': int(time.time()*1000), 'outcome': 'pending',
                    'sdk_before': sdk_counters(self.robot.client)}
        self.motor_mode_diagnostics.append(evidence)
        self.motor_mode_diagnostics = self.motor_mode_diagnostics[-8:]
        self.persist_motor_evidence(evidence, before_command=True)
        try:
            reply = self.robot.client.send_sync_msg(message, timeout=.5)
            result = reply.get_proto() if reply is not None else None
            retcode = getattr(result, '_retcode', None)
            evidence.update({'elapsed_ms': round((time.monotonic()-started)*1000),
                             'sdk_after': sdk_counters(self.robot.client),
                             'reply_received': reply is not None,
                             'retcode': retcode if type(retcode) is int else None,
                             'outcome': 'acknowledged' if type(retcode) is int and retcode == 0
                             else 'no_reply' if reply is None else 'reply_not_successful'})
            self.persist_motor_evidence(evidence)
            if result is None or type(result._retcode) is not int or result._retcode != 0:
                self.motor_failure()
        except ControlError:
            raise
        except Exception as error:  # noqa: BLE001 -- never interpret an exception as acknowledgement
            evidence.update({'outcome': 'exception', 'exception_type': type(error).__name__,
                             'sdk_after': sdk_counters(self.robot.client),
                             'elapsed_ms': round((time.monotonic()-started)*1000)})
            self.persist_motor_evidence(evidence)
            self.motor_failure()
        self.motor_state = 'engaged_reply' if enabled else 'released_reply'
        with self.esc_lock:
            if enabled:
                self.release_at = self.release_ack = None
            else:
                self.release_at = time.monotonic()
                self.release_ack = {'acknowledged_at_ms': int(time.time() * 1000),
                                    'physical_effect_verified': False}
                self.release_evidence.transition(self.release_at, 'released')
                self.esc_stop_at = self.release_at
                self.esc_at = None

    def handle(self, operation, payload):
        with self.lock:
            if operation == 'motor-release':
                if (payload.get('session_id') != self.short_session
                        or payload.get('confirmed_stationary') is not True
                        or not self.motor_stop_id or payload.get('stop_id') != self.motor_stop_id):
                    raise ControlError('請確認本次停止後機體已停穩，再按釋放。', 422)
                self.require_idle()
                if (not self.prepared_idle or not self.control or self.control.lease
                        or self.control.direction != 'stop' or self.control.state == 'fault'
                        or self.control.stop_latched or not self.wheels_at_rest()):
                    raise ControlError('底盤位置、姿態、速度與四輪停穩證據尚未持續確認，或機體有鎖定；不會釋放。', 423)
                if self.motor_state == 'released_reply':
                    return self.status()
                if self.motor_state not in {'holding_zero', 'engaged_reply'}:
                    raise ControlError('電機狀態未確認，請結束驗收。', 423)
                self.set_motor(False)
                return self.status()
            if operation == 'motor-activate':
                # An explicit press first engages, with NO movement in this RPC.
                # The browser must still be held before it sends a separate start.
                self.validate_activation(payload)
                self.motor_attempted = True
                self.motor_press = payload['press_id']
                self.set_motor(True)
                zero_evidence = {'stage': 'zero_stop_after_engage', 'outcome': 'pending',
                    'engage_mode_acknowledged': True, 'ack_timeout_ms': 500,
                    'started_at_ms': int(time.time()*1000),
                    'sdk_before': sdk_counters(self.robot.client)}
                self.motor_mode_diagnostics.append(zero_evidence)
                self.motor_mode_diagnostics = self.motor_mode_diagnostics[-8:]
                self.persist_motor_evidence(zero_evidence)
                zero_started = time.monotonic()
                try:
                    self.control.transport.stop()
                except Exception as error:  # noqa: BLE001 -- isolate failed physical stop acknowledgement
                    zero_evidence.update({'outcome': 'not_acknowledged',
                                          'elapsed_ms': round((time.monotonic()-zero_started)*1000),
                                          'sdk_after': sdk_counters(self.robot.client),
                                          'exception_type': type(error).__name__})
                    self.persist_motor_evidence(zero_evidence)
                    self.motor_failure()
                zero_evidence.update({'outcome': 'acknowledged',
                                     'elapsed_ms': round((time.monotonic()-zero_started)*1000),
                                     'sdk_after': sdk_counters(self.robot.client)})
                self.persist_motor_evidence(zero_evidence)
                return self.status()
            if operation == 'short-press-start' and (
                    self.motor_state != 'engaged_reply' or self.motor_press != payload.get('press_id')):
                raise ControlError('只可由本次按住事件先重新啟用電機；未發出移動。', 423)
            return super().handle(operation, payload)

    def validate_activation(self, payload):
        import re
        press = payload.get('press_id')
        issued = payload.get('issued_at_ms')
        age = int(time.time() * 1000) - issued if type(issued) is int else self.MAX_MS
        if (payload.get('session_id') != self.short_session or not isinstance(press, str)
                or not re.fullmatch(r'[a-f0-9]{32}', press) or payload.get('confirmed_clear_path') is not True
                or not -50 <= age < self.MAX_MS):
            raise ControlError('按鍵資料已過期或未確認，未重新啟用。', 409)
        if (self.motor_attempted or self.short_used or press in self.short_cancelled
                or not self.prepared_idle or not self.control or self.motor_state != 'released_reply'
                or not self.wheels_at_rest()):
            raise ControlError('請先確認停穩並釋放；本次只可重新啟用一次。', 423)
        self.require_idle()

    def status(self):
        result = super().status()
        rest = self.wheels_at_rest()
        return {**result, 'motor_state': self.motor_state, 'motor_stop_id': self.motor_stop_id,
                'rest_evidence_version': 'body-window-v5',
                'motor_transition_version': 'durable-ack-v1',
                'motor_release_receipt': self.release_ack,
                'motor_mode_diagnostics': [dict(item) for item in self.motor_mode_diagnostics],
                'released_observation_seconds': (max(0, int(time.monotonic() - self.release_at))
                    if self.release_at is not None and self.motor_state == 'released_reply' else 0),
                'esc_diagnostics': self.esc_diagnostics(),
                'wheel_rest_confirmed': rest, 'motor_mode_physical_verified': False,
                'movement_enabled': bool(result['movement_enabled'] and rest
                                         and self.motor_state == 'released_reply' and not self.motor_attempted)}
