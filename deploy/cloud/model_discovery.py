"""Explicit staff catalogue search through the existing free search account.

Results link to creators, never proxy unreviewed archives or imply a licence.
No search is sent at startup. The original resident search remains unchanged.
"""
import asyncio
import json
import sqlite3
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from deploy.cloud.gallery_registry import (
    SEARCH_DOMAINS,
    registry_snapshot,
    source_id,
    valid_source_link,
)
from edge_hub.cloud_allowance import CloudAllowance
from edge_hub.estate_services import search_key
from edge_hub.storage_context import current_storage

PATH = '/api/v1/service-desk/model-gallery/search'
SOURCES = SEARCH_DOMAINS


class Search(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    query: str = Field(default='', max_length=80)
    source: str = Field(pattern='^(all|' + '|'.join(SOURCES) + ')$', default='all')
    format: str = Field(pattern='^(all|live2d|vrm)$', default='all')


def creator_url(value):
    return valid_source_link(value)


class ModelDiscovery:
    def __init__(self, quotas, client):
        self.quotas, self.client = quotas, client
        self.cache, self.inflight = {}, {}
        self.tasks = set()
        self.lock = asyncio.Lock()
        self.observation, self.reserved = None, 0
        self.closed = False

    async def close(self):
        self.closed = True
        # A cancelled browser must not abandon a durable reservation thread.
        # Requests are bounded; finish owned work before closing DB/HTTP clients.
        await asyncio.gather(*list(self.tasks), return_exceptions=True)

    async def search(self, request):
        if self.closed:
            raise HTTPException(503, '圖庫搜尋正在結束，請稍後再試。')
        key = (request.source, request.format, request.query.strip())
        cached = self.cache.get(key)
        if cached and time.monotonic() - cached[0] < 21600:
            return {**cached[1], 'cached': True}
        task = self.inflight.get(key)
        if task is None:
            if len(self.inflight) >= 2:
                raise HTTPException(429, '正在搜尋圖庫，請等候完成。')
            task = asyncio.create_task(self.fetch(request))
            self.inflight[key] = task
            self.tasks.add(task)
            def finished(done):
                self.inflight.pop(key, None)
                self.tasks.discard(done)
                if not done.cancelled():
                    done.exception()  # Consume a disconnected caller's result too.
            task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def fetch(self, request):
        async with self.lock:
            snapshot = await self.quotas.reader.snapshot()
            data = snapshot.get('data') or {}
            remaining, limit = data.get('effective_remaining'), data.get('limit')
            if (snapshot.get('status') != 'ok' or type(remaining) is not int or remaining < 2
                    or type(limit) is not int or not 0 < limit <= 1000
                    or data.get('plan') != 'Researcher' or data.get('paygo_used') != 0
                    or data.get('paygo_limit') not in (None, 0)):
                raise HTTPException(503, '未能確認免費搜尋餘額；可先使用下方平台入口，沒有啟用付費搜尋。')
            observation = snapshot.get('updated_at_ms')
            if observation != self.observation:
                self.observation, self.reserved = observation, 0
            if self.reserved + 1 >= remaining:
                raise HTTPException(429, '免費搜尋餘額不足；可使用下方平台入口。')
            storage = current_storage()
            if storage is None:
                raise HTTPException(503, '圖庫搜尋暫未準備好。')
            try:
                await run_in_threadpool(lambda: CloudAllowance(storage.settings_root / 'cloud-usage.sqlite3').reserve({'model_gallery_search_credits': 1}))
            except (ValueError, OSError, RuntimeError, sqlite3.Error):
                raise HTTPException(429, '本月圖庫搜尋預留已用完；居民搜尋不受此分項限制，可直接到作者平台瀏覽。') from None
            self.reserved += 1
        domains = SOURCES[request.source] if request.source != 'all' else [domain for group in SOURCES.values() for domain in group]
        try:
            async with asyncio.timeout(12):
                async with self.client().stream('POST', 'https://api.tavily.com/search',
                        headers={'Authorization': 'Bearer ' + search_key()},
                        json={'query': ('free VRM avatar model ' if request.format == 'vrm' else
                                        'free Live2D model ' if request.format == 'live2d' else
                                        'free Live2D or VRM ready-made avatar model ') + request.query.strip(), 'include_domains': domains,
                              'search_depth': 'basic', 'max_results': 8, 'include_answer': False,
                              'include_images': False, 'include_raw_content': False, 'auto_parameters': False},
                        timeout=10, follow_redirects=False) as response:
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 262144:
                            raise ValueError('bounded_catalogue_response')
            data = json.loads(content)
            items, seen = [], set()
            for item in data.get('results', [])[:8]:
                if not isinstance(item, dict) or not creator_url(item.get('url')):
                    continue
                if request.source != 'all' and not valid_source_link(item['url'], request.source):
                    continue
                parsed = urlsplit(item['url'])
                canonical = urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ''))
                if canonical in seen:
                    continue
                seen.add(canonical)
                items.append({'title': str(item.get('title', '角色模型'))[:140], 'url': canonical,
                              'description': str(item.get('content', ''))[:260],
                              'source': source_id(canonical), 'runtime_verified': False, 'one_click': False})
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
            raise HTTPException(503, '圖庫搜尋暫未完成，未自動重試；可直接到下方平台瀏覽。') from None
        result = {'items': items, 'cached': False, 'licence_verified': False, 'search_credit': 1,
                  'registered_sources': registry_snapshot()['registered_sources'],
                  'connected_sources_goal_complete': False, 'automatic_import': False}
        if len(self.cache) >= 16:
            self.cache.pop(next(iter(self.cache)))
        self.cache[(request.source, request.format, request.query.strip())] = (time.monotonic(), result)
        return result


def discovery_router(authorize, discovery):
    router = APIRouter()

    @router.post(PATH)
    async def search(request: Search):
        authorize()
        return await discovery.search(request)

    return router
