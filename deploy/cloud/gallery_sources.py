"""Bounded, credential-free source discovery; never infer redistribution rights.

Only an already reviewed local manifest can turn a discovered entry into a
one-click archive. Public indexes and creator permission fields stay separate
from verified binary/renderer acceptance. No selected avatar is changed here.
"""
import asyncio
import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from html.parser import HTMLParser

import httpx
from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

PATH = '/api/v1/service-desk/model-gallery/catalogue'
NAMES = ('live2d', 'vtubernook', 'aplaybox')
TTL = 6 * 60 * 60 * 1000
SCHEMA = '''CREATE TABLE cloud_gallery_sources(
 name TEXT PRIMARY KEY,payload TEXT NOT NULL,last_success_ms INTEGER,
 last_attempt_ms INTEGER NOT NULL,etag TEXT NOT NULL,last_modified TEXT NOT NULL,error TEXT NOT NULL)'''


class SourceStore:
    def __init__(self, connect):
        self.connect = connect
        self.write_lock = threading.RLock()

    def initialize(self):
        """Explicit stopped-writer installation only; never called at app boot."""
        with closing(self.connect(False)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute(SCHEMA)
            db.executemany('INSERT INTO cloud_gallery_sources VALUES(?,?,NULL,0,?,?,?)',
                           [(name, '[]', '', '', '') for name in NAMES])

    def rows(self):
        with closing(self.connect(True)) as db:
            records = db.execute('SELECT name,payload,last_success_ms,last_attempt_ms,error FROM cloud_gallery_sources ORDER BY name').fetchall()
        if {row[0] for row in records} != set(NAMES):
            raise ValueError('gallery_source_cache_requires_explicit_installation')
        result = []
        for name, payload, success, attempt, error in records:
            items = json.loads(payload)
            if not isinstance(items, list) or len(items) > 400:
                raise ValueError('invalid_gallery_source_cache')
            result.append({'source': name, 'items': items, 'last_success_ms': success,
                           'last_attempt_ms': attempt, 'error': error, 'stale': bool(error)})
        return result

    def claim(self, name, now, minimum_age=TTL):
        assert name in NAMES
        # One conditional mutation, without holding a remote transaction across
        # a SELECT and another network round trip. Serialize our small writes.
        with self.write_lock, closing(self.connect(False)) as db, db:
            row = db.execute('UPDATE cloud_gallery_sources SET last_attempt_ms=? '
                             'WHERE name=? AND (last_attempt_ms=0 OR last_attempt_ms<=?) RETURNING name',
                             (now, name, now - minimum_age)).fetchone()
            if row is not None:
                return True
            if db.execute('SELECT 1 FROM cloud_gallery_sources WHERE name=?', (name,)).fetchone() is None:
                raise ValueError('gallery_source_cache_requires_explicit_installation')
        return False

    def save(self, name, items, stamp):
        assert name in NAMES and len(items) <= 400
        payload = json.dumps(items, ensure_ascii=False, separators=(',', ':'))
        if len(payload.encode()) > 1024 * 1024:
            raise ValueError('gallery_cache_bound')
        with self.write_lock, closing(self.connect(False)) as db, db:
            db.execute('UPDATE cloud_gallery_sources SET payload=?,last_success_ms=?,error=? WHERE name=?',
                       (payload, stamp, '', name))

    def failed(self, name):
        with self.write_lock, closing(self.connect(False)) as db, db:
            db.execute('UPDATE cloud_gallery_sources SET error=? WHERE name=?', ('source_unavailable_previous_list_retained', name))


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.current = [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            self.current = {'url': attrs.get('href', ''), 'title': ''}

    def handle_data(self, value):
        if self.current is not None:
            self.current['title'] += value + ' '

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.current['title'] = ' '.join(self.current['title'].split())[:180]
            self.links.append(self.current)
            self.current = None


def html_items(text, source):
    parser = Links()
    parser.feed(text)
    items = {}
    for link in parser.links:
        url = link['url']
        if source == 'live2d':
            if url.startswith('/en/learn/sample/'):
                url = 'https://www.live2d.com' + url
            match = re.fullmatch(r'https://www\.live2d\.com/en/learn/sample/([a-z0-9-]+)/?', url)
            if not match or match[1] == 'model-terms':
                continue
        else:
            if url.startswith('/asset/'):
                url = 'https://vtuber-nook.com' + url
            if not re.fullmatch(r'https://vtuber-nook\.com/asset/[0-9]+/[a-z0-9-]+/?', url):
                continue
        if not link['title']:
            continue
        canonical = url.rstrip('/')
        items[canonical] = {'title': link['title'], 'url': canonical,
                            'license_status': 'requires_review', 'format': 'Live2D' if source == 'live2d' else 'mixed'}
    return list(items.values())


def ap_record(row):
    identifier = row.get('work_uuid')
    if not isinstance(identifier, str) or not re.fullmatch('[A-Za-z0-9]{8,20}', identifier):
        return None
    return {'title': str(row.get('work_name', ''))[:180],
            'url': 'https://www.aplaybox.com/details/model/' + identifier,
            'author': str(row.get('nick_name', ''))[:80], 'format': 'Live2D',
            'license_status': 'requires_review', 'download_type': row.get('download_type')}


class SourceCatalogue:
    def __init__(self, store, client, *, now=None):
        self.store, self.client, self.now = store, client, now or (lambda: int(time.time() * 1000))
        self.tasks = set()
        self.closed = False
        self.next_check_ms = 0
        self.next_staff_check_ms = 0
        self.staff_entry_pending = False

    def schedule(self, *, staff_entry=False):
        stamp = self.now()
        next_check = self.next_staff_check_ms if staff_entry else self.next_check_ms
        if self.closed or stamp < next_check:
            return
        if self.tasks:
            # A warm-cache check may be in flight without fetching any source.
            # Do not lose a simultaneous staff-entry request behind that task.
            if staff_entry:
                self.staff_entry_pending = True
            return
        self.next_check_ms = stamp + 60000
        if staff_entry:
            self.next_staff_check_ms = stamp + 60000
        task = asyncio.create_task(self.refresh(minimum_age=60000 if staff_entry else TTL))
        self.tasks.add(task)
        def finished(done):
            self.tasks.discard(done)
            if not done.cancelled():
                done.exception()
            if self.staff_entry_pending and not self.tasks:
                self.staff_entry_pending = False
                self.schedule(staff_entry=True)
        task.add_done_callback(finished)

    async def close(self):
        self.closed = True
        await asyncio.gather(*list(self.tasks), return_exceptions=True)

    async def snapshot(self):
        try:
            rows = await run_in_threadpool(self.store.rows)
            return {'sources': rows, 'refreshing': bool(self.tasks), 'refresh_interval_ms': TTL,
                    'check_on_staff_entry': True, 'entry_coalesce_ms': 60000,
                    'automatic_avatar_switch': False, 'provider_credits_used': 0,
                    'licence_required': True}
        except (OSError, ValueError, sqlite3.Error):
            return {'sources': [], 'refreshing': False, 'cache_unavailable': True,
                    'automatic_avatar_switch': False, 'provider_credits_used': 0}

    async def fetch(self, url, *, payload=None):
        # Call sites contain only fixed first-party endpoints; no user-supplied
        # URL or redirect target is ever followed.
        method = 'POST' if payload is not None else 'GET'
        async with self.client().stream(method, url, json=payload, timeout=12, follow_redirects=False,
                                        headers={'User-Agent': 'NeighbourModelCatalogue/1.0 (public metadata only)'}) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 2 * 1024 * 1024:
                    raise ValueError('source_response_bound')
        return content.decode('utf-8')

    async def collect(self, name):
        if name == 'live2d':
            items = html_items(await self.fetch('https://www.live2d.com/en/learn/sample/'), name)
            if not 1 <= len(items) <= 64:
                raise ValueError('official_index_changed_requires_review')
            return items
        if name == 'vtubernook':
            url = 'https://vtuber-nook.com/category/live2d-3d-pngtuber-models/'
            text = await self.fetch(url)
            pages = [int(value) for value in re.findall(r'live2d-3d-pngtuber-models\?page=([0-9]+)', text)]
            last = max(pages, default=1)
            if not 1 <= last <= 20:
                raise ValueError('nook_index_exceeds_reviewed_bound')
            items = {row['url']: row for row in html_items(text, name)}
            for page in range(2, last + 1):
                for row in html_items(await self.fetch(url + '?page=' + str(page)), name):
                    items[row['url']] = row
            if not items or len(items) > 400:
                raise ValueError('nook_empty_or_large')
            return list(items.values())
        items, last = {}, 1
        for page in range(1, 21):
            payload = {'is_login': 0, 'user_uid': '', 'work_format_id': 5, 'work_category_id': -1,
                       'download_type': -1, 'type': 1, 'keyword': '', 'sort_by': 1,
                       'user_title_type_id': 0, 'current_page': page, 'per_page': 20, 'page_type': 1}
            data = json.loads(await self.fetch('https://api.aplaybox.com/api/web/v1/work/search', payload=payload))
            if data.get('code') != 200:
                raise ValueError('public_index_requires_user_action')
            data = data['data']['result']['data']
            last = data['last_page']
            if type(last) is not int or not 1 <= last <= 20:
                raise ValueError('aplaybox_index_exceeds_reviewed_bound')
            for raw in data['data']:
                row = ap_record(raw)
                if row:
                    items[row['url']] = row
            if page >= last:
                break
        if not items or len(items) > 400:
            raise ValueError('aplaybox_empty_or_large')
        # Permission flags are author-specific, not implied by a "free" badge.
        # Examine a bounded recent sample; never request a download/captcha.
        for row in list(items.values())[:6]:
            payload = {'work_uuid': row['url'].split('/')[-1], 'work_type_id': 1, 'user_uid': '', 'is_login': 0}
            try:
                data = json.loads(await self.fetch('https://api.aplaybox.com/api/web/v1/work/getWorkDetails', payload=payload))
                detail = data['data']['result']['data']
                permissions = {key: detail.get(key) for key in ('allow_commercial', 'allow_redistribute', 'allow_modify')}
                row['permissions'] = permissions
                row['license_status'] = ('redistribution_prohibited' if permissions['allow_redistribute'] == 0
                    else 'permission_declared_binary_review_required' if permissions['allow_redistribute'] == 1
                    else 'requires_review')
            except (httpx.HTTPError, KeyError, ValueError, TypeError):
                pass
        return list(items.values())

    async def refresh(self, *, minimum_age=TTL):
        semaphore = asyncio.Semaphore(2)
        async def one(name):
            try:
                claimed = await run_in_threadpool(self.store.claim, name, self.now(), minimum_age)
            except (OSError, ValueError, sqlite3.Error):
                return False
            if not claimed:
                return True
            try:
                async with semaphore, asyncio.timeout(30):
                    items = await self.collect(name)
                await run_in_threadpool(self.store.save, name, items, self.now())
            except (httpx.HTTPError, TimeoutError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                await run_in_threadpool(self.store.failed, name)
            return True
        checked = await asyncio.gather(*(one(name) for name in NAMES))
        if all(checked):
            self.next_check_ms = self.now() + TTL


def sources_router(authorize, catalogue):
    router = APIRouter()
    @router.get(PATH)
    async def sources():
        authorize()
        snapshot = await catalogue.snapshot()
        catalogue.schedule()
        return {**snapshot, 'refreshing': bool(catalogue.tasks)}
    @router.post(PATH + '/check')
    async def check_sources():
        authorize()
        catalogue.schedule(staff_entry=True)
        return {'refreshing': bool(catalogue.tasks), 'background': True,
                'check_on_staff_entry': True, 'entry_coalesce_ms': 60000}
    return router
