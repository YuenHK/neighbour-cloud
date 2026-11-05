"""Two bounded public catalogue adapters, cached in existing Operations.

No DDL, source archives, credentials or resident data. Zero paid-search calls.
"""
import asyncio
import re
import sqlite3
import threading
from html.parser import HTMLParser

import httpx
from starlette.concurrency import run_in_threadpool

from deploy.cloud.gallery_registry import REGISTRY, safe_title, valid_source_link

NAMESPACE = 'gallery-source-cache-v2'
NAMES = ('booth', 'itch')
TTL = 6 * 60 * 60 * 1000


class ItemLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.current = [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            self.current = {'url': attrs.get('href', ''), 'title': ''}

    def handle_data(self, value):
        if self.current is not None:
            self.current['title'] += value + ' '

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.rows.append(self.current)
            self.current = None


def catalogue_items(text, name):
    parser = ItemLinks()
    parser.feed(text)
    result = {}
    for item in parser.rows:
        title, url = safe_title(item['title']), item['url']
        if not title or not valid_source_link(url, name):
            continue
        if name == 'booth':
            match = re.fullmatch(r'https://(?:[a-zA-Z0-9_-]+\.)?booth\.pm/(?:en/|ja/)?items/([0-9]+)', url)
            if not match:
                continue
            # The same BOOTH item may appear under an author's subdomain.
            url = 'https://booth.pm/en/items/' + match[1]
        elif name == 'itch':
            if not re.fullmatch(r'https://[a-zA-Z0-9_-]+\.itch\.io/[a-zA-Z0-9_-]+/?', url):
                continue
            url = url.rstrip('/')
        else:
            raise ValueError('unreviewed_source_adapter')
        result[url] = {'title': title, 'url': url, 'format': 'unverified',
                       'license_status': 'requires_review', 'price_verified': False,
                       'runtime_verified': False, 'one_click': False}
        if len(result) > 100:
            raise ValueError('catalogue_item_bound')
    if not result:
        raise ValueError('public_index_changed_or_empty')
    return list(result.values())


class ExtraSources:
    def __init__(self, operations, client, now):
        self.operations, self.client, self.now = operations, client, now
        self.lock = threading.RLock()

    def row(self, name):
        if name not in NAMES:
            raise ValueError('unreviewed_source_adapter')
        row = self.operations.get(NAMESPACE, name)
        if row is None:
            return {'source': name, 'items': [], 'last_success_ms': None,
                    'last_attempt_ms': 0, 'error': '', 'stale': False}
        if (not isinstance(row, dict) or row.get('source') != name
                or not isinstance(row.get('items'), list) or len(row['items']) > 100
                or type(row.get('last_attempt_ms')) is not int
                or row['last_attempt_ms'] < 0
                or row.get('last_success_ms') is not None and type(row.get('last_success_ms')) is not int
                or not all(isinstance(item, dict) and valid_source_link(item.get('url'), name)
                           and item.get('one_click') is False and item.get('runtime_verified') is False
                           and item.get('license_status') == 'requires_review' for item in row.get('items', []))):
            raise ValueError('invalid_extended_source_cache')
        return row

    def rows(self):
        result = []
        for name in NAMES:
            try:
                result.append(self.row(name))
            except ValueError:
                # Retain corrupt evidence; do not replace it or hide the
                # original three healthy source caches.
                result.append({'source': name, 'items': [], 'last_success_ms': None,
                               'last_attempt_ms': 0, 'error': 'source_cache_requires_review', 'stale': True})
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

    async def collect(self, name):
        if name not in NAMES:
            raise ValueError('unreviewed_source_adapter')
        async with self.client().stream('GET', REGISTRY[name]['url'], timeout=12, follow_redirects=False,
                headers={'User-Agent': 'NeighbourModelCatalogue/1.0 (public metadata only)'}) as reply:
            reply.raise_for_status()
            if 'text/html' not in reply.headers.get('content-type', '').lower():
                raise ValueError('public_html_required')
            data = bytearray()
            async for chunk in reply.aiter_bytes():
                data.extend(chunk)
                if len(data) > 2 * 1024 * 1024:
                    raise ValueError('source_response_bound')
        return catalogue_items(data.decode('utf-8'), name)

    async def refresh(self, minimum_age=TTL):
        # At most two new HTTP requests per due staff check; no pagination,
        # candidate downloads, permissions/captcha pages or fallback proxy.
        for name in NAMES:
            try:
                claimed = await run_in_threadpool(self.claim, name, minimum_age)
            except (ValueError, sqlite3.Error, OSError):
                continue
            if not claimed:
                continue
            try:
                async with asyncio.timeout(15):
                    items = await self.collect(name)
            except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError):
                await run_in_threadpool(self.complete, name)
            else:
                await run_in_threadpool(self.complete, name, items)
