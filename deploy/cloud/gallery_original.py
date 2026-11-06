"""Check original creator metadata without executing or downloading models."""
import asyncio
import hashlib
import json
import re
import sqlite3
from pathlib import Path

import httpx
from starlette.concurrency import run_in_threadpool

from deploy.cloud.gallery_extra import ExtraSources
from deploy.cloud.gallery_registry import valid_source_link

SOURCE = 'desktop-companion'
NAMESPACE = 'gallery-original-cache-v1'
ORIGIN = 'https://github.com/xShiroeNguyenx/desktop-companion'
RAW = 'https://raw.githubusercontent.com/xShiroeNguyenx/desktop-companion/main/'
PINNED_LICENSE_SHA256 = '71509e96ebfe54db9466105e681d694bc3c30cc3f12d398fabb3f79f1b9d6114'
CATALOGUE = Path(__file__).resolve().parents[2] / 'airi_overlay/cloud-model-gallery.json'


def original_items(text, known_hashes):
    data = json.loads(text)
    if not isinstance(data, dict) or data.get('format') != 1 or not isinstance(data.get('models'), list) or not 1 <= len(data['models']) <= 100:
        raise ValueError('original_manifest_changed_requires_review')
    items, seen = [], set()
    for row in data['models']:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not re.fullmatch(r'[a-z][a-z0-9-]{1,60}', row['id'])
                or type(row.get('version')) is not int or not 1 <= row['version'] <= 10000
                or row.get('file') != f"{row['id']}-{row['version']}.zip"
                or type(row.get('size')) is not int or not 1 <= row['size'] <= 32 * 1024 * 1024
                or not isinstance(row.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', row['sha256'])
                or row['id'] in seen):
            raise ValueError('original_model_descriptor_invalid')
        seen.add(row['id'])
        if row['sha256'] not in known_hashes:
            items.append({'title': row['id'].replace('-', ' ').title(),
                'url': ORIGIN + '/releases/download/models/' + row['file'], 'format': 'live2d',
                'sha256': row['sha256'], 'bytes': row['size'], 'license_status': 'requires_review',
                'runtime_verified': False, 'one_click': False})
    return items


class OriginalUpdates(ExtraSources):
    """Reuse the existing owned cache/claim lifecycle; only its own namespace."""
    def row(self, name=SOURCE):
        if name != SOURCE:
            raise ValueError('unreviewed_source_adapter')
        row = self.operations.get(NAMESPACE, SOURCE)
        if row is None:
            return {'source': SOURCE, 'items': [], 'last_success_ms': None, 'last_attempt_ms': 0, 'error': '', 'stale': False}
        if (not isinstance(row, dict) or row.get('source') != SOURCE or not isinstance(row.get('items'), list)
                or len(row['items']) > 100 or type(row.get('last_attempt_ms')) is not int
                or row['last_attempt_ms'] < 0 or row.get('last_success_ms') is not None and type(row['last_success_ms']) is not int
                or not all(isinstance(item, dict) and valid_source_link(item.get('url'), SOURCE)
                    and item.get('runtime_verified') is False and item.get('one_click') is False
                    and item.get('license_status') == 'requires_review' for item in row['items'])):
            raise ValueError('original_source_cache_requires_review')
        return row

    def rows(self):
        try:
            return [self.row()]
        except ValueError:
            return [{'source': SOURCE, 'items': [], 'last_success_ms': None, 'last_attempt_ms': 0,
                     'error': 'source_cache_requires_review', 'stale': True}]

    def claim(self, name, minimum_age):
        with self.lock:
            row = self.row(name)
            if row['last_attempt_ms'] and self.now() - row['last_attempt_ms'] < minimum_age:
                return False
            self.operations.put(NAMESPACE, SOURCE, {**row, 'last_attempt_ms': self.now()})
            return True

    def complete(self, name, items=None):
        with self.lock:
            row = self.row(name)
            if items is None:
                row.update(error='source_unavailable_previous_list_retained', stale=True)
            else:
                row.update(items=items, last_success_ms=self.now(), error='', stale=False)
            self.operations.put(NAMESPACE, SOURCE, row)

    async def fetch(self, path):
        assert path in ('ASSETS-LICENSE.md', 'models/manifest.json')
        async with self.client().stream('GET', RAW + path, timeout=10, follow_redirects=False,
                headers={'User-Agent': 'NeighbourModelCatalogue/1.0 (public metadata only)'}) as reply:
            reply.raise_for_status()
            data = bytearray()
            async for chunk in reply.aiter_bytes():
                data.extend(chunk)
                if len(data) > 512 * 1024:
                    raise ValueError('original_metadata_bound')
            return bytes(data)

    async def refresh(self, minimum_age):
        try:
            if not await run_in_threadpool(self.claim, SOURCE, minimum_age):
                return
            async with asyncio.timeout(15):
                license_text = await self.fetch('ASSETS-LICENSE.md')
                if hashlib.sha256(license_text).hexdigest() != PINNED_LICENSE_SHA256:
                    raise ValueError('original_license_changed_requires_review')
                text = await self.fetch('models/manifest.json')
                known = {row['original_sha256'] for row in json.loads(CATALOGUE.read_text(encoding='utf-8'))['models']
                         if row['id'].startswith(SOURCE + '-') and row.get('original_sha256')}
                items = original_items(text, known)
            await run_in_threadpool(self.complete, SOURCE, items)
        except (httpx.HTTPError, TimeoutError, UnicodeError, ValueError, KeyError, sqlite3.Error, OSError):
            try:
                await run_in_threadpool(self.complete, SOURCE)
            except (ValueError, sqlite3.Error, OSError):
                pass  # Preserve corrupt evidence; never clear original caches.
