import asyncio
import hashlib
import json
import sqlite3

import httpx
import pytest

from deploy.cloud import gallery_original as original
from deploy.cloud.gallery_original import NAMESPACE, OriginalUpdates, original_items
from deploy.cloud.operations import Operations, migrate


def manifest(**updates):
    row = {'id': 'pink-future', 'version': 1, 'file': 'pink-future-1.zip', 'size': 100, 'sha256': 'a' * 64}
    row.update(updates)
    return json.dumps({'format': 1, 'models': [row]})


def test_known_original_hashes_are_not_reintroduced_and_new_versions_remain_unreviewed():
    assert original_items(manifest(), {'a' * 64}) == []
    [row] = original_items(manifest(version=2, file='pink-future-2.zip', sha256='b' * 64), {'a' * 64})
    assert row['format'] == 'live2d' and row['url'].startswith(original.ORIGIN + '/releases/download/models/')
    assert row['one_click'] is False and row['runtime_verified'] is False and row['license_status'] == 'requires_review'


@pytest.mark.parametrize('updates', [
    {'file': '../pink.zip'}, {'file': 'https://evil.test/model.zip'}, {'id': '../private'},
    {'version': True}, {'version': 0}, {'sha256': 'G' * 64}, {'size': True}, {'size': 32 * 1024 * 1024 + 1},
])
def test_untrusted_manifest_fields_never_become_fetch_targets(updates):
    with pytest.raises(ValueError):
        original_items(manifest(**updates), set())


def test_duplicate_ids_and_unbounded_lists_are_rejected():
    row = json.loads(manifest())['models'][0]
    for rows in ([row, row], [row] * 101):
        with pytest.raises(ValueError):
            original_items(json.dumps({'format': 1, 'models': rows}), set())


def test_background_check_coalesces_retains_old_list_and_never_downloads_or_changes_original_data(monkeypatch, tmp_path):
    async def run():
        db = sqlite3.connect(':memory:', check_same_thread=False)
        migrate(db)
        operations = Operations(db, b'isolated-original-gallery-test-key')
        operations.put('sentinel-original', 'preserve', {'quota': 99, 'paused': True})
        catalogue = tmp_path / 'models.json'
        catalogue.write_text(json.dumps({'models': []}))
        monkeypatch.setattr(original, 'CATALOGUE', catalogue)
        license_text = b'Creator fixture CC BY-NC 4.0'
        monkeypatch.setattr(original, 'PINNED_LICENSE_SHA256', hashlib.sha256(license_text).hexdigest())
        calls, now = [], [1000]

        def handler(request):
            calls.append(str(request.url))
            assert not request.headers.get('authorization')
            assert request.url.host == 'raw.githubusercontent.com'
            assert request.url.path.endswith(('ASSETS-LICENSE.md', 'models/manifest.json'))
            if now[0] > 1000:
                return httpx.Response(429)
            return httpx.Response(200, content=license_text if request.url.path.endswith('.md') else manifest().encode())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = OriginalUpdates(operations, lambda: client, lambda: now[0])
            assert source.rows()[0]['last_success_ms'] is None and operations.count(NAMESPACE) == 0
            await source.refresh(60000)
            assert len(calls) == 2
            before = source.row()
            assert len(before['items']) == 1 and before['last_success_ms'] == 1000
            now[0] += 59999
            await source.refresh(60000)
            assert len(calls) == 2
            now[0] += 1
            await source.refresh(60000)
            after = source.row()
            assert len(calls) == 3 and after['stale']
            assert after['items'] == before['items'] and after['last_success_ms'] == before['last_success_ms']
            assert operations.get('sentinel-original', 'preserve') == {'quota': 99, 'paused': True}
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['license-change', 'redirect', 'oversize'])
def test_changed_licensing_redirects_or_large_metadata_do_not_grant_import_rights(monkeypatch, failure):
    async def run():
        db = sqlite3.connect(':memory:', check_same_thread=False)
        migrate(db)
        operations = Operations(db, b'isolated-original-gallery-test-key')
        calls = []
        monkeypatch.setattr(original, 'PINNED_LICENSE_SHA256', hashlib.sha256(b'expected').hexdigest())

        def handler(request):
            calls.append(str(request.url))
            if failure == 'redirect':
                return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
            return httpx.Response(200, content=b'changed' if failure == 'license-change' else b'x' * (512 * 1024 + 1))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = OriginalUpdates(operations, lambda: client, lambda: 1000)
            await source.refresh(60000)
            assert len(calls) == 1 and source.row()['last_success_ms'] is None
            assert source.row()['stale'] and not source.row()['items']
            assert operations.count('gallery-source-cache-v2') == 0
    asyncio.run(run())
