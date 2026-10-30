"""One local inference at a time; FIFO turns, no queued images or robot commands."""
import threading
from collections import deque
from contextlib import contextmanager


class PatrolCancelled(Exception):
    pass


class PatrolTurns:
    def __init__(self, limit=8):
        self.condition = threading.Condition()
        self.pending = deque()
        self.active = None
        self.limit = limit

    @contextmanager
    def turn(self, device, cancelled):
        with self.condition:
            if device == self.active or device in self.pending or len(self.pending)+(self.active is not None) >= self.limit:
                raise PatrolCancelled()
            self.pending.append(device)
            try:
                while self.active is not None or self.pending[0] != device:
                    if cancelled():
                        raise PatrolCancelled()
                    self.condition.wait(.1)
                if cancelled():
                    raise PatrolCancelled()
                self.pending.popleft()
                self.active = device
            except BaseException:
                self.pending.remove(device)
                self.condition.notify_all()
                raise
        try:
            yield
        finally:
            with self.condition:
                self.active = None
                self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            return {'active': self.active, 'waiting': list(self.pending), 'capacity': self.limit}
