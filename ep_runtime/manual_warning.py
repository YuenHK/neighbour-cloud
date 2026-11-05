"""Manual trajectory LED + notification sound. Never access firing or motion."""
import threading
import time

from edge_hub.robot_control import ControlError


class ManualWarning:
    def __init__(self, duration=3, clock=time.monotonic):
        self.duration, self.clock = duration, clock
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.thread = None
        self.last_started = float('-inf')
        self.result = {'state': 'idle', 'led_ack': False, 'sound_ack': False}

    def snapshot(self):
        with self.lock:
            return dict(self.result)

    def start(self, robot):
        if robot is None:
            raise ControlError('請先手動連線 EP。', 409)
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ControlError('警示正在進行，沒有重複觸發。', 409)
            if self.clock()-self.last_started < 10:
                raise ControlError('請稍候再發出警示。', 429)
            self.last_started = self.clock()
            self.cancel = threading.Event()
            self.result = {'state': 'starting', 'led_ack': False, 'sound_ack': False}

        def perform():
            deadline = self.clock()+self.duration
            result = {'state': 'unconfirmed', 'led_ack': False, 'sound_ack': False, 'standby_led_ack': False,
                      'trajectory_led_ack': False, 'trajectory_off_ack': False}
            try:
                # Dedicated LED interface only. Never call Blaster.fire (default: gel beads).
                result['trajectory_led_ack'] = robot.blaster.set_led(brightness=255, effect='on') is True
                result['led_ack'] = robot.led.set_led(comp='bottom_all', r=255, g=160, b=0, effect='breath') is True
                if not self.cancel.is_set():
                    # Factory notification sound, once. No arbitrary audio IDs or repeat count.
                    action = robot.play_sound(sound_id=0x104, times=1)
                    if action is not None:
                        action.wait_for_completed(timeout=2)
                        result['sound_ack'] = action.has_succeeded is True
                self.cancel.wait(max(0, deadline-self.clock()))
            except Exception:  # noqa: BLE001 -- isolate SDK, never retry physical effects
                result['state'] = 'unconfirmed'
            finally:
                try:
                    result['trajectory_off_ack'] = robot.blaster.set_led(brightness=0, effect='off') is True
                except Exception:  # noqa: BLE001 -- best effort off, no firing fallback or retry
                    result['trajectory_off_ack'] = False
                try:
                    result['standby_led_ack'] = robot.led.set_led(comp='bottom_all', r=0, g=180, b=160, effect='on') is True
                except Exception:  # noqa: BLE001
                    result['standby_led_ack'] = False
                result['state'] = 'completed' if all(result[key] for key in (
                    'led_ack', 'sound_ack', 'standby_led_ack', 'trajectory_led_ack', 'trajectory_off_ack')) else 'unconfirmed'
                with self.lock:
                    self.result = result
        self.thread = threading.Thread(target=perform, daemon=True, name='ep-manual-warning')
        self.thread.start()
        return {'warning': self.snapshot(), 'requested': True, 'physical_effect_verified': False}

    def stop(self):
        self.cancel.set()
        if self.thread:
            self.thread.join(timeout=1)
