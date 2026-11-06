"""Two reviewed original libraries: bounded metadata checks, never model downloads.

Source notices are pinned independently of the dynamic index. New versions stay
unreviewed until archive/native validation; existing usable models remain cached.
"""
import asyncio
import hashlib
import json
import re
import sqlite3
from urllib.parse import quote

import httpx
from starlette.concurrency import run_in_threadpool

from deploy.cloud.gallery_extra import ExtraSources
from deploy.cloud.gallery_registry import valid_source_link

NAMESPACE = 'gallery-curated-original-cache-v1'
CONFIG = {
    'psd2live': {
        'origin': 'https://github.com/tsunehimatoi/psd2live-examples',
        'license': 'https://raw.githubusercontent.com/tsunehimatoi/psd2live-examples/main/LICENSE',
        'index': 'https://raw.githubusercontent.com/tsunehimatoi/psd2live-examples/main/scripts/fixtures.lock.json',
        'license_sha256': 'a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499',
    },
    'mofox': {
        'origin': 'https://github.com/MoFox-Studio/MoFox-ArtCollection',
        'license': 'https://raw.githubusercontent.com/MoFox-Studio/MoFox-ArtCollection/main/README.md',
        'index': 'https://api.github.com/repos/MoFox-Studio/MoFox-ArtCollection/git/trees/main?recursive=1',
        'license_sha256': 'f06fac854c81b306f89442518e80ce8a99109cbbb7f555e965a5b8d55d0e7b7e',
    },
}


def candidate_items(name, text, known):
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError('curated_index_requires_review')
    items = []
    if name == 'psd2live':
        rows = data.get('fixtures') if isinstance(data, dict) else None
        if data.get('schema_version') != 1 or not isinstance(rows, list) or not 1 <= len(rows) <= 40:
            raise ValueError('curated_index_requires_review')
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('archive'), dict):
                raise TypeError('curated_descriptor_requires_review')
            identity, archive = row.get('id'), row.get('archive', {})
            url, digest, size = archive.get('url'), archive.get('sha256'), archive.get('size_bytes')
            if (not isinstance(identity, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,60}', identity)
                    or not valid_source_link(url, name) or not url.startswith(CONFIG[name]['origin'] + '/releases/download/')
                    or not url.endswith('.zip') or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)
                    or type(size) is not int or not 0 < size <= 1024 * 1024 * 1024):
                raise ValueError('curated_descriptor_requires_review')
            if digest not in known:
                items.append({'title': identity.replace('_', ' ').title(), 'url': url, 'sha256': digest, 'bytes': size})
    elif name == 'mofox':
        rows = data.get('tree') if isinstance(data, dict) else None
        if data.get('truncated') or not re.fullmatch(r'[a-f0-9]{40}', data.get('sha', '')) or not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError('curated_tree_requires_review')
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError('curated_tree_asset_requires_review')
            path = row.get('path', '')
            if row.get('type') != 'blob' or not isinstance(path, str) or not path.startswith('Live2d/') or not path.endswith('.zip'):
                continue
            if (len(path) > 240 or any(part in ('', '.', '..') for part in path.split('/'))
                    or not re.fullmatch(r'[a-f0-9]{40}', row.get('sha', '')) or type(row.get('size')) is not int
                    or not 0 < row['size'] <= 32 * 1024 * 1024):
                raise ValueError('curated_tree_asset_requires_review')
            if row['sha'] not in known:
                items.append({'title': path.rsplit('/', 1)[-1][:-4], 'url': CONFIG[name]['origin'] + '/blob/' + data['sha'] + '/' + quote(path),
                    'git_blob_sha1': row['sha'], 'bytes': row['size']})
    else:
        raise ValueError('unreviewed_source_adapter')
    if len(items) > 40 or len({row['url'] for row in items}) != len(items):
        raise ValueError('curated_index_duplicate_or_bound')
    return [dict(row, format='live2d', license_status='requires_review', runtime_verified=False, one_click=False) for row in items]


class CuratedUpdates(ExtraSources):
    def row(self, name):
        if name not in CONFIG:
            raise ValueError('unreviewed_source_adapter')
        row = self.operations.get(NAMESPACE, name)
        if row is None:
            return {'source': name, 'items': [], 'last_success_ms': None, 'last_attempt_ms': 0, 'error': '', 'stale': False}
        if (not isinstance(row, dict) or row.get('source') != name or not isinstance(row.get('items'), list)
                or len(row['items']) > 40 or type(row.get('last_attempt_ms')) is not int or row['last_attempt_ms'] < 0
                or row.get('last_success_ms') is not None and type(row['last_success_ms']) is not int
                or not all(isinstance(item, dict) and valid_source_link(item.get('url'), name)
                    and item.get('one_click') is False and item.get('runtime_verified') is False
                    and item.get('license_status') == 'requires_review' for item in row['items'])):
            raise ValueError('curated_cache_requires_review')
        return row

    def rows(self):
        result = []
        for name in CONFIG:
            try:
                result.append(self.row(name))
            except ValueError:
                result.append({'source': name, 'items': [], 'last_success_ms': None, 'last_attempt_ms': 0,
                    'error': 'source_cache_requires_review', 'stale': True})
        return result

    def claim(self, name, minimum_age):
        with self.lock:
            row = self.row(name)
            if row['last_attempt_ms'] and self.now() - row['last_attempt_ms'] < minimum_age:
                return False
            self.operations.put(NAMESPACE, name, {**row, 'last_attempt_ms': self.now()})
            return True

    def complete(self, name, items=None):
        with self.lock:
            row = self.row(name)
            if items is None:
                row.update(error='source_unavailable_previous_list_retained', stale=True)
            else:
                row.update(items=items, last_success_ms=self.now(), error='', stale=False)
            self.operations.put(NAMESPACE, name, row)

    async def fetch(self, url):
        if url not in {config[key] for config in CONFIG.values() for key in ('license', 'index')}:
            raise ValueError('unreviewed_source_endpoint')
        async with self.client().stream('GET', url, timeout=10, follow_redirects=False,
                headers={'User-Agent': 'NeighbourModelCatalogue/1.0 (public metadata only)'}) as reply:
            reply.raise_for_status()
            data = bytearray()
            async for chunk in reply.aiter_bytes():
                data.extend(chunk)
                if len(data) > 512 * 1024:
                    raise ValueError('curated_metadata_bound')
            return bytes(data)

    async def refresh(self, minimum_age):
        async def one(name):
            try:
                if not await run_in_threadpool(self.claim, name, minimum_age):
                    return
                async with asyncio.timeout(15):
                    license_text = await self.fetch(CONFIG[name]['license'])
                    if hashlib.sha256(license_text).hexdigest() != CONFIG[name]['license_sha256']:
                        raise ValueError('curated_license_changed_requires_review')
                    text = await self.fetch(CONFIG[name]['index'])
                    from deploy.cloud.gallery_original import CATALOGUE
                    known = {row['upstream_digest'] for row in json.loads(CATALOGUE.read_text(encoding='utf-8'))['models']
                        if row.get('update_source') == name and row.get('upstream_digest')}
                    items = candidate_items(name, text, known)
                await run_in_threadpool(self.complete, name, items)
            except (httpx.HTTPError, TimeoutError, UnicodeError, ValueError, KeyError, TypeError, sqlite3.Error, OSError):
                try:
                    await run_in_threadpool(self.complete, name)
                except (ValueError, sqlite3.Error, OSError):
                    pass
        await asyncio.gather(*(one(name) for name in CONFIG))
