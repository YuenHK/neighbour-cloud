import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deploy.cloud import model_discovery as module


@pytest.mark.parametrize('url,valid', [('https://artist.booth.pm/items/1', True),
    ('https://author.itch.io/model', True), ('https://www.aplaybox.com/details/model/test', True), ('https://vtuber-nook.com/resource/model', True), ('https://www.live2d.com/zh-CHS/learn/sample/', True), ('https://nizima.com/Item/DetailItem/1', True),
    ('https://itch.io.evil.test/model', False), ('http://127.0.0.1/model', False),
    ('https://user:secret@artist.booth.pm/model', False), ('https://artist.booth.pm:8443/model', False)])
def test_only_public_creator_links(url, valid):
    assert module.creator_url(url) is valid


def test_official_free_quota_required_before_reservation_or_search(monkeypatch):
    async def run():
        for status, data in [('stale', {'limit': 1000, 'effective_remaining': 900}),
                             ('ok', {'limit': 5000, 'effective_remaining': 900}),
                             ('ok', {'limit': 1000, 'effective_remaining': 1}), ('unavailable', {})]:
            async def snapshot(status=status, data=data):
                return {'status': status, 'data': data}
            value = module.ModelDiscovery(SimpleNamespace(reader=SimpleNamespace(snapshot=snapshot)), lambda: pytest.fail('no request'))
            with pytest.raises(HTTPException):
                await value.search(module.Search(query='cat'))
    asyncio.run(run())


def test_concurrent_search_coalesces_and_cached_lookup_spends_no_more(monkeypatch, tmp_path):
    reservations, requests = [], []
    monkeypatch.setattr(module, 'current_storage', lambda: SimpleNamespace(settings_root=tmp_path))
    monkeypatch.setattr(module, 'CloudAllowance', lambda _: SimpleNamespace(reserve=lambda x: reservations.append(x)))
    monkeypatch.setattr(module, 'search_key', lambda: 'synthetic-key')
    async def run():
        async def snapshot():
            return {'status': 'ok', 'updated_at_ms': 1, 'data': {'limit': 1000, 'effective_remaining': 50, 'plan': 'Researcher', 'paygo_used': 0, 'paygo_limit': None}}
        async def handler(request):
            requests.append(request)
            await asyncio.sleep(.01)
            return httpx.Response(200, json={'results': [{'title': '<script>untrusted</script>', 'url': 'https://artist.itch.io/model', 'content': 'Public model'}, {'url': 'https://private.invalid/key'}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            value = module.ModelDiscovery(SimpleNamespace(reader=SimpleNamespace(snapshot=snapshot)), lambda: client)
            first, second = await asyncio.gather(*(value.search(module.Search(query='cat', source='itch')) for _ in range(2)))
            assert first == second and len(first['items']) == 1
            assert first['licence_verified'] is False
            assert (await value.search(module.Search(query='cat', source='itch')))['cached'] is True
            assert len(requests) == len(reservations) == 1 and not value.tasks
            assert 'api_key' not in requests[0].content.decode() and requests[0].headers['Authorization'] == 'Bearer synthetic-key'
    asyncio.run(run())


def test_explicit_post_and_staff_authorization():
    app = FastAPI()
    def deny():
        raise HTTPException(403)
    app.include_router(module.discovery_router(deny, None))
    with TestClient(app) as client:
        assert client.get(module.PATH).status_code == 405
        assert client.post(module.PATH, json={'query': 'cat'}).status_code == 403
        assert client.post(module.PATH, json={'query': 'x'*81}).status_code == 422


def test_disconnect_keeps_owned_work_and_shutdown_waits(monkeypatch, tmp_path):
    monkeypatch.setattr(module, 'current_storage', lambda: SimpleNamespace(settings_root=tmp_path))
    reservations = []
    monkeypatch.setattr(module, 'CloudAllowance', lambda _: SimpleNamespace(reserve=lambda x: reservations.append(x)))
    monkeypatch.setattr(module, 'search_key', lambda: 'synthetic-key')
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def snapshot():
            return {'status': 'ok', 'updated_at_ms': 1, 'data': {'limit': 1000, 'effective_remaining': 10, 'plan': 'Researcher', 'paygo_used': 0, 'paygo_limit': None}}
        async def handler(_request):
            entered.set()
            await release.wait()
            return httpx.Response(200, json={'results': []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            value = module.ModelDiscovery(SimpleNamespace(reader=SimpleNamespace(snapshot=snapshot)), lambda: client)
            caller = asyncio.create_task(value.search(module.Search(query='cat')))
            await entered.wait()
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert len(value.tasks) == len(reservations) == 1
            closing = asyncio.create_task(value.close())
            await asyncio.sleep(0)
            assert not closing.done()
            release.set()
            await closing
            assert not value.tasks
            with pytest.raises(HTTPException):
                await value.search(module.Search(query='cat'))
    asyncio.run(run())
