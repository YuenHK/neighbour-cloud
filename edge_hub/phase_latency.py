"""Content-free process-local phase timings; never a playback acceptance claim."""
import math
import threading
import time
from collections import deque
from contextlib import contextmanager

ALLOWED = {'gemma_response_ready', 'azure_complete', 'local_recognition'}


class PhaseLatency:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = {}

    @contextmanager
    def measure(self, name):
        if name not in ALLOWED:
            raise ValueError('unknown_phase')
        started = time.monotonic()
        success = False
        try:
            yield
            success = True
        finally:
            with self.lock:
                row = self.rows.setdefault(name, {'samples': deque(maxlen=128), 'count': 0, 'failed': 0})
                row['count'] += 1
                row['failed'] += int(not success)
                row['samples'].append((time.monotonic()-started)*1000)

    def snapshot(self):
        with self.lock:
            result = {}
            for name, row in self.rows.items():
                values = sorted(row['samples'])
                result[name] = {'count': row['count'], 'failed': row['failed'], 'window_samples': len(values),
                                'p50_ms': round(values[math.ceil(len(values)*.5)-1], 2),
                                'p95_ms': round(values[math.ceil(len(values)*.95)-1], 2)}
            return {'scope': 'process-local phase wall time; not end-to-end audible latency', 'phases': result}


phase_latency = PhaseLatency()
