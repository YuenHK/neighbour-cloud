"""Stage four: one explicitly held forward pulse, fixed minimum speed."""
import re
import secrets
import time

from edge_hub.robot_control import ControlError, RobotCommand
from ep_runtime.readonly_session import PreparedIdleEpSession


class ShortPressEpSession(PreparedIdleEpSession):
    MAX_MS = 200
    STAGE = 4

    def __init__(self, *args, **kwargs):
        self.short_session = secrets.token_hex(16)
        self.short_used = False
        self.short_press = None
        self.short_cancelled = set()
        self.short_lease = None
        self.short_stop_origin = None
        super().__init__(*args, **kwargs)

    def handle(self, operation, payload):
        if operation not in {'short-press-start', 'short-press-release'}:
            return super().handle(operation, payload)
        with self.lock:
            self.last_request = time.monotonic()
            press_id = payload.get('press_id')
            if (payload.get('session_id') != self.short_session or not isinstance(press_id, str)
                    or not re.fullmatch(r'[a-f0-9]{32}', press_id)):
                raise ControlError('本次短按資料已過期，請結束驗收。', 409)
            if operation == 'short-press-release':
                source = payload.get('source', 'release')
                if source not in {'release', 'limit', 'blur', 'cancel', 'disconnect', 'pagehide'}:
                    raise ControlError('停止來源不符。', 422)
                if len(self.short_cancelled) >= 32 and press_id not in self.short_cancelled:
                    raise ControlError('短按取消資料過多，請結束驗收。', 409)
                self.short_cancelled.add(press_id)
                if self.short_press is None:
                    self.short_used = True  # fence a start which arrives after release
                if (self.short_press == press_id and self.control and self.short_lease
                        and self.control.lease == self.short_lease):
                    try:
                        self.control.command(RobotCommand(lease_token=self.short_lease, seq=1,
                            issued_at_ms=int(time.time() * 1000), ttl_ms=self.MAX_MS, direction='stop'))
                        if self.control.reason == 'operator_release' and self.control.state != 'fault':
                            self.short_stop_origin = source
                    except ControlError:
                        if (self.control.lease is not None or self.control.direction != 'stop'
                                or self.control.state == 'fault'):
                            raise
                return self.status()
            if press_id in self.short_cancelled:
                return self.status()
            if self.short_used:
                raise ControlError('本次短按已用過；請結束並回報，不會重試。', 409)
            if payload.get('confirmed_clear_path') is not True:
                raise ControlError('請先在現場確認前方空曠及可以關機。', 422)
            issued = payload.get('issued_at_ms')
            age = int(time.time() * 1000) - issued if type(issued) is int else self.MAX_MS
            if not -50 <= age < self.MAX_MS:
                raise ControlError('短按已過期，未發出移動。', 409)
            if not self.prepared_idle or not self.control or self.drive_mode != 'chassis_lead':
                raise ControlError('請先完成本次控制模式準備。', 423)
            self.require_idle()
            self.short_used, self.short_press = True, press_id
            self.speed_level = self.control.transport.speed_level = 1
            lease = self.control.acquire()
            self.short_lease = lease['lease_token']
            self.control.command(RobotCommand(lease_token=self.short_lease, seq=0,
                issued_at_ms=issued, ttl_ms=self.MAX_MS, direction='forward'))
            return self.status()

    def status(self):
        reason = self.control.reason if self.control else None
        origin = ('cancelled_before_start' if self.short_used and self.short_press is None else
                  'host_limit' if reason == 'command_timeout' else
                  self.short_stop_origin if reason == 'operator_release' else None)
        return {**super().status(), 'acceptance_stage': self.STAGE, 'short_press_session': self.short_session,
                'short_press_used': self.short_used, 'short_press_max_ms': self.MAX_MS,
                'short_press_stop_origin': origin,
                'short_press_speed_mps': .15,
                'movement_enabled': bool(self.prepared_idle and not self.short_used and self.control
                    and not self.control.stop_latched and self.control.state != 'fault' and self.grounded())}


class ReleaseCheckEpSession(ShortPressEpSession):
    """Stage five separates early human release from the host time limit."""
    MAX_MS = 500
    STAGE = 5
