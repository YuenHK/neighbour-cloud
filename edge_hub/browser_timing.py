"""Bounded, client-reported durations. Never collect utterances or resident IDs."""
import math
import threading
from collections import deque
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from edge_hub.service_desk import local_resident_request


class Timing(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    marks: dict[Literal['asr_ready', 'first_text', 'first_audio_scheduled', 'response_complete', 'audio_complete', 'failed', 'cancelled'], float] = Field(max_length=7)


class BrowserTimings:
    def __init__(self):
        self.lock = threading.Lock()
        self.values = {name: deque(maxlen=128) for name in ('asr_ready', 'first_text', 'first_audio_scheduled', 'response_complete', 'audio_complete', 'failed', 'cancelled')}

    def snapshot(self):
        with self.lock:
            result = {}
            for name, raw in self.values.items():
                values = sorted(raw)
                result[name] = {'samples':len(values), 'p50_ms':values[math.ceil(len(values)*.5)-1] if values else None,
                                'p95_ms':values[math.ceil(len(values)*.95)-1] if values else None}
            return {'scope':'untrusted browser-reported elapsed from submit or VAD-end (includes ASR/merge when voice); audio scheduled, not audible acceptance', 'stages':result}


browser_timings = BrowserTimings()


def timing_router(*, resident_request=None, timings=None):
    timings = browser_timings if timings is None else timings
    router = APIRouter()
    @router.post('/api/v1/resident/timing')
    def receive(body: Timing, request: Request):
        if not (local_resident_request if resident_request is None else resident_request)(request):
            raise HTTPException(403)
        if any(not math.isfinite(value) or not 0 <= value <= 180000 for value in body.marks.values()):
            raise HTTPException(422, 'invalid duration')
        with timings.lock:
            for name, value in body.marks.items():
                timings.values[name].append(value)
        return {'accepted':True}
    return router
