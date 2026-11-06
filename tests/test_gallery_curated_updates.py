import asyncio
import hashlib
import json
import sqlite3

import httpx
import pytest

from deploy.cloud import gallery_curated as curated
from deploy.cloud.operations import Operations, migrate


def fixtures(digest='a' * 64, **updates):
    row = {'id': 'new-hero', 'archive': {'url': curated.CONFIG['psd2live']['origin'] + '/releases/download/v1/hero.zip',
        'sha256': digest, 'size_bytes': 1234}}
    row.update(updates)
    return json.dumps({'schema_version': 1, 'fixtures': [row]})


def tree(**updates):
    row = {'type': 'blob', 'path': 'Live2d/new-hero.zip', 'size': 12, 'sha': 'c' * 40}
    row.update(updates)
    return json.dumps({'sha': 'd' * 40, 'truncated': False, 'tree': [row]})


def test_known_originals_are_not_rediscovered_and_new_binary_is_not_auto_certified():
    assert curated.candidate_items('psd2live', fixtures(), {'a' * 64}) == []
    assert curated.candidate_items('mofox', tree(), {'c' * 40}) == []
    for name, text in [('psd2live', fixtures()), ('mofox', tree())]:
        [item] = curated.candidate_items(name, text, set())
        assert item['one_click'] is False and item['runtime_verified'] is False
        assert item['license_status'] == 'requires_review'


@pytest.mark.parametrize('text', ['null', '[]', '{}', '{"schema_version":1,"fixtures":[null]}',
    fixtures(archive={'url': 'https://evil.test/a.zip', 'sha256': 'a' * 64, 'size_bytes': 100}),
    fixtures(archive={'url': curated.CONFIG['psd2live']['origin'] + '/releases/download/v1/a.zip', 'sha256': 'bad', 'size_bytes': True})])
def test_malformed_manifest_never_grants_rights_or_expands_fetch_targets(text):
    with pytest.raises((ValueError, TypeError)):
        curated.candidate_items('psd2live', text, set())


@pytest.mark.parametrize('text', [tree(path='Live2d/../secret.zip'), tree(size=True), tree(sha='bad'),
    json.dumps({'sha': 'd' * 40, 'truncated': True, 'tree': []})])
def test_untrusted_tree_is_rejected(text):
    with pytest.raises(ValueError):
        curated.candidate_items('mofox', text, set())


def test_background_refresh_coalesces_and_retains_old_list_when_license_changes(monkeypatch, tmp_path):
    async def run():
        db = sqlite3.connect(':memory:', check_same_thread=False)
        migrate(db)
        ops = Operations(db, b'isolated-curated-gallery-test-key')
        ops.put('sentinel-original', 'preserve', {'quota': 99, 'paused': True})
        from deploy.cloud import gallery_original
        path = tmp_path / 'catalogue.json'
        path.write_text('{"models":[]}')
        monkeypatch.setattr(gallery_original, 'CATALOGUE', path)
        config = {name: dict(value, license_sha256=hashlib.sha256(b'synthetic original licence').hexdigest()) for name, value in curated.CONFIG.items()}
        monkeypatch.setattr(curated, 'CONFIG', config)
        stamp, calls = [1000], []

        def handler(request):
            calls.append(str(request.url))
            assert not request.headers.get('authorization')
            assert not request.headers.get('cookie')
            for name, value in config.items():
                if str(request.url) == value['license']:
                    return httpx.Response(200, content=b'synthetic original licence' if stamp[0] == 1000 else b'changed terms')
                if str(request.url) == value['index']:
                    return httpx.Response(200, text=fixtures() if name == 'psd2live' else tree())
            raise AssertionError('Unexpected download or endpoint')

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = curated.CuratedUpdates(ops, lambda: client, lambda: stamp[0])
            await adapter.refresh(60000)
            old = adapter.rows()
            assert len(calls) == 4 and all(len(row['items']) == 1 for row in old)
            await adapter.refresh(60000)
            assert len(calls) == 4
            stamp[0] += 60000
            await adapter.refresh(60000)
            assert len(calls) == 6  # Changed terms stop before requesting index.
            for before, after in zip(old, adapter.rows(), strict=True):
                assert after['stale'] and after['items'] == before['items']
                assert after['last_success_ms'] == before['last_success_ms']
            assert ops.get('sentinel-original', 'preserve') == {'quota': 99, 'paused': True}
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['redirect', 'oversize', 'rate-limit'])
def test_failed_metadata_is_bounded_and_no_redirect_or_retry(failure):
    async def run():
        db = sqlite3.connect(':memory:', check_same_thread=False)
        migrate(db)
        ops = Operations(db, b'isolated-curated-gallery-test-key')
        calls = []
        def handler(request):
            calls.append(str(request.url))
            if failure == 'redirect':
                return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
            if failure == 'rate-limit':
                return httpx.Response(429)
            return httpx.Response(200, content=b'x' * (512 * 1024 + 1))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = curated.CuratedUpdates(ops, lambda: client, lambda: 1000)
            await adapter.refresh(60000)
            assert len(calls) == 2 and all(row['stale'] and not row['items'] for row in adapter.rows())
            with pytest.raises(ValueError):
                await adapter.fetch('http://127.0.0.1/private')
    asyncio.run(run())
