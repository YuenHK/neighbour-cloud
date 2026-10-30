"""Bound distinct network synthesis jobs, sharing only concurrent identical work."""
import threading
from concurrent.futures import Future


class SynthesisFlights:
    def __init__(self, parallel=2):
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(parallel)
        self.pending = {}

    def run(self, key, generate):
        with self.lock:
            future = self.pending.get(key)
            owner = future is None
            if owner:
                if len(self.pending) >= 16:
                    raise RuntimeError('synthesis queue full')
                future = self.pending[key] = Future()
        if not owner:
            return future.result(timeout=35)
        try:
            if not self.slots.acquire(timeout=5):
                raise RuntimeError('synthesis busy')
            try:
                result = generate()
            finally:
                self.slots.release()
            future.set_result(result)
            return result
        except BaseException as error:
            future.set_exception(error)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)
