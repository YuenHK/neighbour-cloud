"""Operator-held toy infrared tag signal only; no gel beads or motion access."""
import threading
import time
from collections import deque

from edge_hub.robot_control import ControlError


class InfraredWarning:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.closed = deque(maxlen=256)
        self.press = None
        self.deadline = 0
        self.cancel = threading.Event()
        self.thread = None
        self.state = 'idle'

    def update(self, robot, press, active):
        with self.lock:
            if not active:
                self.closed.append(press)
                if self.press == press:
                    self.cancel.set()
                return {'state': 'stopping'}
            if press in self.closed:
                raise ControlError('按鍵已放開，未重新啟動。', 409)
            if robot is None:
                raise ControlError('請先手動連線。', 409)
            if self.thread and self.thread.is_alive():
                if self.press != press or self.cancel.is_set():
                    raise ControlError('上一個警示尚未結束。', 409)
                self.deadline = self.clock()+1.5
                return {'state': self.state}
            self.press, self.deadline = press, self.clock()+1.5
            self.cancel = threading.Event()
            self.state = 'active'

            def run():
                sound = None
                try:
                    if robot.blaster.set_led(brightness=255, effect='on') is not True:
                        raise RuntimeError('light unconfirmed')
                    while not self.cancel.is_set() and self.clock() < self.deadline:
                        with self.lock:
                            if self.cancel.is_set() or self.clock() >= self.deadline:
                                break
                            # NEVER omit fire_type: SDK default is water, not infrared.
                            if robot.blaster.fire(fire_type='ir', times=1) is not True:
                                raise RuntimeError('infrared unconfirmed')
                            if not self.cancel.is_set() and (sound is None or sound.has_succeeded is True):
                                sound = robot.play_sound(sound_id=0x104, times=1)
                        self.cancel.wait(.2)
                        if robot.blaster.set_led(brightness=0, effect='off') is not True:
                            raise RuntimeError('light off unconfirmed')
                        self.cancel.wait(.3)
                        if (not self.cancel.is_set() and self.clock() < self.deadline
                                and robot.blaster.set_led(brightness=255, effect='on') is not True):
                            raise RuntimeError('light on unconfirmed')
                    self.state = 'stopped'
                except Exception:  # noqa: BLE001 -- stop on failure; no fallback or retry
                    self.state = 'unconfirmed'
                finally:
                    try:
                        if robot.blaster.set_led(brightness=0, effect='off') is not True:
                            self.state = 'unconfirmed'
                    except Exception:  # noqa: BLE001
                        self.state = 'unconfirmed'
                    with self.lock:
                        self.closed.append(press)
            self.thread = threading.Thread(target=run, daemon=True, name='ep-held-infrared')
            self.thread.start()
            return {'state': self.state}

    def stop(self):
        with self.lock:
            self.cancel.set()
            if self.press:
                self.closed.append(self.press)
