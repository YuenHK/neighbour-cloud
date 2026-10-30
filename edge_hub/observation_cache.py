"""Exact JPEG result reuse only; no perceptual skip of small new hazards."""
import hashlib
import threading
import time
from collections import OrderedDict


class ObservationCache:
    def __init__(self, clock=time.monotonic):
        self.clock=clock
        self.lock=threading.Lock()
        self.values=OrderedDict()

    def key(self, jpeg, restricted):
        return hashlib.sha256(jpeg).hexdigest(), bool(restricted)

    def get(self, jpeg, restricted):
        key=self.key(jpeg,restricted)
        with self.lock:
            row=self.values.get(key)
            if row is None or self.clock()-row[0] > 30:
                self.values.pop(key,None)
                return None
            return set(row[1])

    def put(self, jpeg, restricted, findings):
        with self.lock:
            key=self.key(jpeg,restricted)
            self.values[key]=(self.clock(),frozenset(findings))
            self.values.move_to_end(key)
            while len(self.values)>16:
                self.values.popitem(last=False)
