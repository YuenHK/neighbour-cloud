import asyncio
import json
import sqlite3
from functools import wraps

import httpx
import pytest

from deploy.cloud.gallery_sources import NAMES, TTL, SourceCatalogue, SourceStore, html_items


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


@pytest.fixture
def store(tmp_path):
    path = tmp_path / 'catalogue.sqlite3'
    def connect(readonly):
        return sqlite3.connect(path.as_uri() + ('?mode=ro' if readonly else '?mode=rwc'), uri=True)
    result = SourceStore(connect)
    result.initialize()
    return result


def test_html_only_first_party_real_model_links():
    text = '''<a href="https://evil.test/x">bad</a><a href="/en/learn/sample/kei/">Kei</a>
      <a href="https://www.live2d.com/en/learn/sample/model-terms/">terms</a>
      <a href="javascript:alert(1)">bad</a><a href="/en/learn/sample/kei/">duplicate</a>'''
    result = html_items(text, 'live2d')
    assert len(result) == 1 and result[0]['url'].endswith('/kei')
    assert result[0]['license_status'] == 'requires_review'


def test_cache_and_failed_refresh_survive_restart_without_touching_old_items(store):
    item = {'title': 'old model', 'url': 'https://vtuber-nook.com/asset/1/model'}
    assert store.claim('vtubernook', 1000)
    store.save('vtubernook', [item], 1000)
    restarted = SourceStore(store.connect)
    assert not restarted.claim('vtubernook', 1000 + TTL - 1)
    assert restarted.claim('vtubernook', 1000 + TTL)
    restarted.failed('vtubernook')
    row = next(row for row in restarted.rows() if row['source'] == 'vtubernook')
    assert row['items'] == [item] and row['last_success_ms'] == 1000 and row['stale']


@async_test
async def test_pagination_rights_and_shutdown_no_paid_or_download_calls(store):
    calls = []
    def handler(request):
        calls.append(request)
        assert not request.headers.get('authorization')
        if request.url.host == 'www.live2d.com':
            return httpx.Response(200, text='<a href="/en/learn/sample/kei/">Kei</a>')
        if request.url.host == 'vtuber-nook.com':
            page = request.url.params.get('page', '1')
            return httpx.Response(200, text=f'<a href="/asset/{page}/cat">Cat {page}</a>'
                                  '<a href="/category/live2d-3d-pngtuber-models?page=2">Next</a>')
        payload = json.loads(request.content)
        if request.url.path.endswith('/search'):
            assert payload['work_format_id'] == 5 and payload['is_login'] == 0
            row = {'work_uuid': 'Abcd1234', 'work_name': 'Live2D', 'nick_name': 'Author'}
            data = {'last_page': 1, 'data': [row]}
        else:
            assert request.url.path.endswith('/getWorkDetails')
            data = {'allow_redistribute': 0, 'allow_commercial': 0, 'allow_modify': 1}
        return httpx.Response(200, json={'code': 200, 'data': {'result': {'data': data}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalogue = SourceCatalogue(store, lambda: client, now=lambda: 1000)
        catalogue.schedule()
        catalogue.schedule()
        assert len(catalogue.tasks) == 1
        await asyncio.gather(*list(catalogue.tasks))
        catalogue.schedule()
        assert not catalogue.tasks  # Warm launches do not reopen three DB transactions.
        await catalogue.close()
        snapshot = await catalogue.snapshot()
        assert len(calls) == 5
        assert {row['source'] for row in snapshot['sources']} == set(NAMES)
        nook = next(row for row in snapshot['sources'] if row['source'] == 'vtubernook')
        assert len(nook['items']) == 2
        ap = next(row for row in snapshot['sources'] if row['source'] == 'aplaybox')
        assert ap['items'][0]['license_status'] == 'redistribution_prohibited'
        assert snapshot['automatic_avatar_switch'] is False and snapshot['provider_credits_used'] == 0
        restarted = SourceCatalogue(store, lambda: client, now=lambda: 1001)
        await restarted.refresh()
        assert len(calls) == 5


@async_test
async def test_unbounded_pagination_or_login_preserves_cache(store):
    store.save('vtubernook', [{'title': 'retained'}], 99)
    def handler(request):
        return httpx.Response(200, text='<a href="/category/live2d-3d-pngtuber-models?page=100000">Next</a>')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        c = SourceCatalogue(store, lambda: client, now=lambda: 1000)
        await c.refresh()
    row = next(row for row in store.rows() if row['source'] == 'vtubernook')
    assert row['items'] == [{'title': 'retained'}] and row['stale']


@async_test
async def test_every_staff_entry_checks_again_but_polling_and_fast_reload_coalesce(store):
    stamp = [1000]
    calls = []
    class Catalogue(SourceCatalogue):
        async def collect(self, name):
            calls.append((name, stamp[0]))
            return [{'title': 'public metadata', 'url': 'https://www.live2d.com/en/learn/sample/kei'}]
    c = Catalogue(store, None, now=lambda: stamp[0])
    c.schedule(staff_entry=True)
    await asyncio.gather(*list(c.tasks))
    assert len(calls) == 3
    stamp[0] += 59999
    c.schedule(staff_entry=True)
    assert not c.tasks
    stamp[0] += 1
    c.schedule()  # Ordinary GET polling still respects its six-hour cache.
    assert not c.tasks
    c.schedule(staff_entry=True)
    await asyncio.gather(*list(c.tasks))
    assert len(calls) == 6
    restarted = Catalogue(store, None, now=lambda: stamp[0] + 1)
    await restarted.refresh(minimum_age=60000)
    assert len(calls) == 6  # Persistent guard also works after a process restart.
    assert (await c.snapshot())['check_on_staff_entry']


@async_test
async def test_staff_entry_during_warm_cache_check_is_not_lost(store):
    for name in NAMES:
        assert store.claim(name, 1000)
        store.save(name, [{'title': 'cached'}], 1000)
    calls = []
    class Catalogue(SourceCatalogue):
        async def collect(self, name):
            calls.append(name)
            return [{'title': 'fresh'}]
    c = Catalogue(store, None, now=lambda: 61000)
    c.schedule()  # No source due at the six-hour threshold.
    c.schedule(staff_entry=True)
    assert c.staff_entry_pending
    while c.tasks:
        await asyncio.gather(*list(c.tasks))
        await asyncio.sleep(0)
    assert sorted(calls) == sorted(NAMES)
    assert all(row['last_success_ms'] == 61000 for row in store.rows())
