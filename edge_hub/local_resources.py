"""Bounded, cached, read-only whole-notebook utilization; no process/file inventory."""
import asyncio
import time
from pathlib import Path

import psutil
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse


def sample():
    result = {}
    def memory():
        value = psutil.virtual_memory()
        return value.percent, value.total-value.available, value.total
    def storage():
        value = psutil.disk_usage(str(Path(__file__).resolve().parents[1]))
        return value.percent, value.used, value.total
    probes = {'cpu': lambda: (psutil.cpu_percent(interval=.1), None, None),
              'ram': memory, 'storage': storage}
    for name, probe in probes.items():
        try:
            percent, used, total = probe()
            result[name] = {'percent': percent, 'used_bytes': used, 'total_bytes': total}
        except (OSError, RuntimeError, ValueError, TypeError):
            result[name] = {'percent': None, 'used_bytes': None, 'total_bytes': None}
    return {'metrics': result, 'scope': 'whole_notebook', 'storage_scope': 'project_drive',
            'updated_at_ms': int(time.time()*1000)}


def resources_router(authorize, sampler=sample):
    router = APIRouter()
    lock, cached, at = asyncio.Lock(), None, 0

    @router.get('/api/v1/service-desk/resources')
    async def resources(x_operator_key: str | None = Header(default=None)):
        nonlocal cached, at
        authorize(x_operator_key)
        async with lock:
            if cached is None or time.monotonic()-at >= 4:
                cached = await asyncio.to_thread(sampler)
                at = time.monotonic()
        return JSONResponse(cached, headers={'Cache-Control': 'no-store'})

    return router
