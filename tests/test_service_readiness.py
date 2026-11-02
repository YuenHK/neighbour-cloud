import asyncio

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from edge_hub.service_readiness import Readiness, readiness_router


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr('edge_hub.service_readiness.cloudflare_gemma.configuration', lambda: {'plan': 'Free'})
    monkeypatch.setattr('edge_hub.service_readiness.cloudflare_gemma.state', lambda: {'cooldown': False})
    monkeypatch.setattr('edge_hub.service_readiness.azure_voice.status', lambda: {'configured': True, 'blocked': False})


def test_passive_checks_are_local_only_coalesced_bounded_and_refresh_after_failure():
    calls, broken, now = [], [False], [0.0]
    def respond(request):
        assert request.method == 'GET'
        assert request.url.host == '127.0.0.1'
        calls.append(str(request.url))
        if request.url.port == 8765:
            if broken[0]:
                raise httpx.ConnectError('synthetic failure')
            return httpx.Response(200, json={'status': 'ok', 'stt': True, 'tts_engine': 'azure-hiumaan-f0'})
        assert request.url.port == 4173
        return httpx.Response(200, headers={'Content-Type': 'text/html'}, text='<div id="app"></div>')
    readiness = Readiness(transport=httpx.MockTransport(respond), clock=lambda: now[0])
    async def run():
        a, b = await asyncio.gather(readiness.snapshot(), readiness.snapshot())
        assert a == b and a['ready'] and len(calls) == 2
        assert not a['cloud_probed'] and not a['ep_probed']
        now[0] += 4
        broken[0] = True
        result = await readiness.snapshot()
        assert not result['ready']
        assert not next(row for row in result['checks'] if row['id'] == 'speech')['ready']
        now[0] += 4
        broken[0] = False
        assert (await readiness.snapshot())['ready']
        assert len(calls) == 6
    asyncio.run(run())


def test_bad_page_and_audio_shape_do_not_become_ready():
    def respond(request):
        return httpx.Response(200, json=['not', 'health'])
    readiness = Readiness(transport=httpx.MockTransport(respond))
    result = asyncio.run(readiness.snapshot())
    assert not result['ready']
    assert {row['id'] for row in result['checks'] if not row['ready']} == {'speech', 'recognition', 'page'}


def test_authentication_runs_before_probe_and_response_has_no_cache():
    calls = []
    def authorize(key):
        if key != 'test-staff':
            raise HTTPException(403)
    class Checks:
        async def snapshot(self):
            calls.append(True)
            return {'ready': True}
    app = FastAPI()
    app.include_router(readiness_router(authorize, Checks()))
    with TestClient(app) as client:
        assert client.get('/api/v1/service-desk/readiness').status_code == 403
        assert calls == []
        response = client.get('/api/v1/service-desk/readiness', headers={'X-Operator-Key': 'test-staff'})
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        assert calls == [True]
