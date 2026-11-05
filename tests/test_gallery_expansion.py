import asyncio
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from deploy.cloud import model_discovery
from deploy.cloud.gallery_extra import NAMESPACE, ExtraSources, catalogue_items
from deploy.cloud.gallery_registry import REGISTRY, registry_snapshot, valid_source_link
from deploy.cloud.gallery_sources import SourceCatalogue, SourceStore, sources_router
from deploy.cloud.model_discovery import Search
from deploy.cloud.operations import Operations, migrate


def operations():
    db = sqlite3.connect(':memory:', check_same_thread=False)
    migrate(db)
    return Operations(db, b'synthetic-gallery-fixture-key-00000')


def test_source_registry_distinguishes_metadata_and_pinned_runtime_sources_from_full_integrations():
    value = registry_snapshot()
    assert len(REGISTRY) == value['registered_sources'] == 21
    assert len({row['domains'][0] for row in value['items']}) == 21
    assert value['target_complete'] is False and value['all_sources_one_click'] is False
    assert value['metadata_adapters'] == 5 and value['existing_oauth_sources'] == 1
    assert value['reviewed_runtime_sources'] == 7 and value['reviewed_runtime_models'] == 9
    assert value['reviewed_original_github_models'] == 39
    assert value['verified_independent_sources'] == 16 and value['github_original_sources'] == 13
    assert {row['id'] for row in value['items'] if row['one_click_verified']} == {'vrmconsortium', 'tsukuyomi', 'aituber-onair'}
    for row in value['items']:
        assert valid_source_link(row['url'], row['id'])
        assert row['note'] and row['terms'].startswith('https://')
        assert Search(source=row['id']).source == row['id']
    with pytest.raises(ValidationError):
        Search(source='https://127.0.0.1')
    with pytest.raises(ValidationError):
        Search(format='spine')


@pytest.mark.parametrize('url', [
    'https://booth.pm.evil.test/en/items/1', 'https://user:pw@booth.pm/en/items/1',
    'https://127.0.0.1/', 'http://booth.pm/en/items/1', 'https://booth.pm:8080/en/items/1',
    'https://booth.pm/\ncredential', None, 1,
])
def test_registry_never_expands_to_arbitrary_fetch_targets(url):
    assert not valid_source_link(url)


def test_booth_normalises_author_aliases_deduplicates_and_does_not_grant_runtime_or_price():
    items = catalogue_items('''<a href="https://artist.booth.pm/items/123">First</a>
      <a href="https://booth.pm/en/items/123">Same model</a>
      <a href="https://booth.pm/users/sign_in">Sign in</a>
      <a href="https://evil.test/model.vrm">External</a>
      <a href="javascript:alert(1)">Invalid</a>''', 'booth')
    assert len(items) == 1 and items[0]['url'] == 'https://booth.pm/en/items/123'
    assert items[0]['license_status'] == 'requires_review'
    assert not items[0]['one_click'] and not items[0]['runtime_verified'] and not items[0]['price_verified']


def test_itch_reads_only_item_pages_not_download_checkout_or_assets():
    items = catalogue_items('''<a href="https://artist.itch.io/model">Actual model</a>
      <a href="https://artist.itch.io/model/download/key">Download</a>
      <a href="https://itch.io/checkout/1">Checkout</a>
      <a href="https://artist.itch.io">Author</a>
      <a href="https://static.itch.io/main.css">Style</a>''', 'itch')
    assert [row['url'] for row in items] == ['https://artist.itch.io/model']
    with pytest.raises(ValueError, match='empty'):
        catalogue_items('<html>Login required</html>', 'itch')


def test_extra_cache_survives_failure_and_restart_does_not_touch_existing_operations():
    async def run():
        ops, now, calls = operations(), [1000], []
        ops.put('sentinel-original', 'unchanged', {'quota': 123, 'paused': True})
        def handler(request):
            calls.append(str(request.url))
            assert not request.headers.get('authorization')
            if now[0] > 1000:
                return httpx.Response(503)
            text = ('<a href="https://booth.pm/en/items/123">Public model</a>' if request.url.host == 'booth.pm'
                    else '<a href="https://author.itch.io/model">Another model</a>')
            return httpx.Response(200, text=text, headers={'content-type': 'text/html'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            extra = ExtraSources(ops, lambda: client, lambda: now[0])
            await extra.refresh(60000)
            assert len(calls) == 2
            before = extra.rows()
            now[0] += 59999
            await ExtraSources(ops, lambda: client, lambda: now[0]).refresh(60000)
            assert len(calls) == 2
            now[0] += 1
            await extra.refresh(60000)
            after = extra.rows()
            assert len(calls) == 4
            for old, current in zip(before, after, strict=True):
                assert current['stale'] and current['items'] == old['items']
                assert current['last_success_ms'] == old['last_success_ms']
            assert ops.get('sentinel-original', 'unchanged') == {'quota': 123, 'paused': True}
    asyncio.run(run())


def test_extra_redirect_and_oversize_are_not_followed_or_promoted():
    async def run():
        for kind in ('redirect', 'oversize'):
            calls, ops = [], operations()
            def handler(request, calls=calls, kind=kind):
                calls.append(request)
                if kind == 'redirect':
                    return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
                return httpx.Response(200, text='x'*(2*1024*1024+1), headers={'content-type': 'text/html'})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                extra = ExtraSources(ops, lambda: client, lambda: 1000)
                await extra.refresh()
            assert len(calls) == 2
            assert all(row['stale'] and not row['items'] and row['last_success_ms'] is None for row in extra.rows())
    asyncio.run(run())


def test_registry_requires_staff_and_does_not_schedule_sources():
    app, calls = FastAPI(), []
    def authorize():
        calls.append('auth')
        raise HTTPException(403)
    app.include_router(sources_router(authorize, None))
    with TestClient(app) as client:
        assert client.get('/api/v1/service-desk/model-gallery/catalogue/registry').status_code == 403
    assert calls == ['auth']


def test_snapshot_combines_five_metadata_sources_without_creating_or_migrating_tables(tmp_path):
    path = tmp_path / 'original.sqlite3'
    def connect(readonly):
        return sqlite3.connect(path.as_uri() + ('?mode=ro' if readonly else '?mode=rwc'), uri=True)
    original = SourceStore(connect)
    original.initialize()
    ops = operations()
    value = SourceCatalogue(original, None, operations=ops)
    snapshot = asyncio.run(value.snapshot())
    assert len(snapshot['sources']) == 5
    assert snapshot['metadata_sources_with_success'] == 0
    assert snapshot['unreviewed_items_importable'] is False
    assert ops.count(NAMESPACE) == 0  # Reading is not implicit cache installation.
    with connect(True) as db:
        assert [row[0] for row in db.execute('SELECT name FROM sqlite_master WHERE type="table"')] == ['cloud_gallery_sources']


def test_extra_corrupt_cache_never_overwrites_or_claims_success():
    ops = operations()
    ops.put(NAMESPACE, 'booth', {'bad': 'retain evidence'})
    with pytest.raises(ValueError, match='invalid_extended'):
        ExtraSources(ops, None, lambda: 1000).row('booth')
    assert ops.get(NAMESPACE, 'booth') == {'bad': 'retain evidence'}


def test_search_source_and_format_are_in_cache_key_and_results_cannot_escape_selected_source(monkeypatch, tmp_path):
    reservations, calls = [], []
    monkeypatch.setattr(model_discovery, 'current_storage', lambda: SimpleNamespace(settings_root=tmp_path))
    monkeypatch.setattr(model_discovery, 'CloudAllowance', lambda _: SimpleNamespace(reserve=lambda x: reservations.append(x)))
    monkeypatch.setattr(model_discovery, 'search_key', lambda: 'synthetic-test-key')
    async def run():
        async def snapshot():
            return {'status': 'ok', 'updated_at_ms': 1,
                    'data': {'limit': 1000, 'effective_remaining': 100, 'plan': 'Researcher', 'paygo_used': 0, 'paygo_limit': 0}}
        def handler(request):
            import json
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={'results': [
                {'title': 'same', 'url': 'https://artist.itch.io/model#first'},
                {'title': 'duplicate', 'url': 'https://artist.itch.io/model#second'},
                {'title': 'wrong source', 'url': 'https://booth.pm/en/items/1'},
            ]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            discovery = model_discovery.ModelDiscovery(SimpleNamespace(reader=SimpleNamespace(snapshot=snapshot)), lambda: client)
            vrm = await discovery.search(Search(source='itch', query='anime', format='vrm'))
            live2d = await discovery.search(Search(source='itch', query='anime', format='live2d'))
            assert len(vrm['items']) == len(live2d['items']) == 1
            assert vrm['items'][0]['url'] == 'https://artist.itch.io/model'
            assert vrm['items'][0]['source'] == 'itch' and vrm['automatic_import'] is False
            assert vrm['connected_sources_goal_complete'] is False
            assert (await discovery.search(Search(source='itch', query='anime', format='vrm')))['cached']
            await discovery.close()
        assert len(calls) == len(reservations) == 2
        assert 'free VRM' in calls[0]['query'] and 'free Live2D' in calls[1]['query']
        assert calls[0]['include_domains'] == ['itch.io']
    asyncio.run(run())
