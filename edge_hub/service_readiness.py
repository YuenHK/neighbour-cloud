"""Passive local dependency checks. Never probe a model, synthesize or contact EP."""
import asyncio
import time

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from edge_hub import azure_voice, cloudflare_gemma


class Readiness:
    def __init__(self, *, transport=None, clock=time.monotonic):
        self.transport, self.clock = transport, clock
        self.lock = asyncio.Lock()
        self.last = None
        self.until = 0

    async def snapshot(self):
        async with self.lock:
            if self.last is not None and self.clock() < self.until:
                return self.last
            async with httpx.AsyncClient(transport=self.transport, trust_env=False, follow_redirects=False,
                                         timeout=httpx.Timeout(1.2)) as client:
                async def audio():
                    try:
                        response = await client.get('http://127.0.0.1:8765/health')
                        if response.status_code == 200 and len(response.content) <= 256000:
                            data = response.json()
                            if data.get('status') == 'ok':
                                return data
                    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                        pass
                    return {}

                async def stage():
                    try:
                        response = await client.get('http://127.0.0.1:4173/ui/estate-resident-entry.html')
                        return (response.status_code == 200 and len(response.content) <= 256000
                                and 'text/html' in response.headers.get('content-type', '')
                                and 'id="app"' in response.text)
                    except (httpx.HTTPError, ValueError):
                        return False
                sound, page = await asyncio.gather(audio(), stage())
            try:
                chat = bool(cloudflare_gemma.configuration()) and not cloudflare_gemma.state()['cooldown']
                voice = azure_voice.status()
                speech = voice['configured'] and not voice['blocked'] and sound.get('tts_engine') == 'azure-hiumaan-f0'
            except (OSError, ValueError, TypeError, KeyError):
                chat, speech = False, False
            checks = [
                {'id': 'chat', 'label': '對話設定', 'ready': chat},
                {'id': 'speech', 'label': '曉曼朗讀', 'ready': bool(speech)},
                {'id': 'recognition', 'label': '本機辨識', 'ready': sound.get('stt') is True},
                {'id': 'page', 'label': '數字人頁面', 'ready': bool(page)},
            ]
            self.last = {'ready': all(row['ready'] for row in checks), 'checks': checks,
                         'checked_at_ms': round(time.time()*1000),
                         'scope': 'local_settings_and_http_only', 'cloud_probed': False, 'ep_probed': False}
            self.until = self.clock()+3
            return self.last


def readiness_router(authorize, checks=None):
    router = APIRouter()
    checks = checks or Readiness()

    @router.get('/api/v1/service-desk/readiness')
    async def snapshot(x_operator_key: str | None = Header(default=None)):
        authorize(x_operator_key)
        return JSONResponse(await checks.snapshot(), headers={'Cache-Control': 'no-store'})
    return router
