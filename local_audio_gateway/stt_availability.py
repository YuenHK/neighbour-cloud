"""Bounded cloud-STT recovery; never retries or stores an audio request."""
from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Awaitable, Callable

from fastapi import HTTPException


class SttAvailability:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 deadline: float = 30, cooldown: float = 15):
        if not all(math.isfinite(value) and 0 < value <= 60 for value in (deadline, cooldown)):
            raise ValueError('invalid STT timing')
        self._clock = clock
        self._deadline = deadline
        self._cooldown = cooldown
        self._lock = threading.Lock()
        self._retry_at = 0.0
        self._reason = 'not_checked'
        self._probe = False
        self._failures = 0

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {'scope': 'process-local cloud request outcomes; not microphone acceptance',
                    'last_result': self._reason, 'failures': self._failures,
                    'retry_after_seconds': max(0, math.ceil(self._retry_at - self._clock())),
                    'probe_in_flight': self._probe, 'automatic_retries': False}

    async def run(self, operation: Callable[[], Awaitable[str]]) -> str:
        with self._lock:
            remaining = self._retry_at - self._clock()
            if remaining > 0 or self._probe:
                raise HTTPException(503, '語音供應商暫時未就緒，稍後可重新說話；未重傳錄音。',
                                    headers={'Retry-After': str(max(1, math.ceil(remaining)))})
            recovering = self._retry_at > 0
            if recovering:
                self._probe = True
        try:
            async with asyncio.timeout(self._deadline):
                text = await operation()
        except TimeoutError as exc:
            self._failed('deadline_exceeded')
            raise HTTPException(504, '語音辨識等待逾時；未自動重傳錄音。',
                                headers={'Retry-After': str(math.ceil(self._cooldown))}) from exc
        except HTTPException as exc:
            if exc.status_code in {429, 502, 503, 504}:
                self._failed('upstream_unavailable' if exc.status_code != 429 else 'usage_limited')
            raise
        else:
            with self._lock:
                self._retry_at = 0.0
                self._reason = 'succeeded'
            return text
        finally:
            if recovering:
                with self._lock:
                    self._probe = False

    def _failed(self, reason: str) -> None:
        with self._lock:
            self._failures += 1
            self._reason = reason
            self._retry_at = self._clock() + self._cooldown
