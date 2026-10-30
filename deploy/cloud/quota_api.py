"""Read-only cloud staff quota view: persistent reservations are not balances.

Only Tavily exposes a usage API here. No inference, speech, billing, account
discovery, native dashboard snapshot, quota reset or history service is queried.
"""
import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from edge_hub import azure_voice, cloudflare_gemma
from edge_hub.api_quota import QuotaReader
from edge_hub.cloud_allowance import LIMITS
from edge_hub.estate_services import search_key
from edge_hub.quota_overview import counter
from edge_hub.storage_context import current_storage
from edge_hub.usage_snapshot import usage_snapshot

QUOTA_PATH = '/api/v1/service-desk/quota'
QUOTA_DEADLINE = 6
HK = timezone(timedelta(hours=8))


def local_overview(*, now=None):
    storage = current_storage()
    if storage is None:
        raise RuntimeError('explicit_cloud_storage_required')
    stamp = (now or datetime.now(UTC)).astimezone(UTC)
    snapshot = usage_snapshot(storage.settings_root / 'cloud-usage.sqlite3',
                              (stamp.strftime('%Y-%m-%d'), stamp.strftime('%Y-%m')))

    def guard(meter):
        interval, limit = LIMITS[meter]
        period = stamp.strftime('%Y-%m' if interval == 'month' else '%Y-%m-%d')
        when = ((stamp.replace(day=28) + timedelta(days=4)).replace(day=1) if interval == 'month'
                else stamp + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        value = counter(snapshot.get((meter, period), 0) if snapshot is not None else None, limit)
        return {'status': 'ok' if snapshot is not None else 'unavailable', 'interval': interval,
                'reset_at': when.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'period': '系統守護下次重設：' + when.astimezone(HK).strftime('%Y-%m-%d %H:%M（香港）'),
                'percent': value['percent'], 'counters': [{**value, 'meter': meter}]}

    def operation(names, guard, configured):
        try:
            flags = [storage.controls.read(name) for name in names]
            if names == ('azure-voice-control.json',):
                state = 'paused' if flags[0]['paused'] else 'ready'
            else:
                state = ('blocked' if datetime.fromisoformat(flags[0]['until']) > stamp else
                         'cooling' if datetime.fromisoformat(flags[1]['until']) > stamp else 'ready')
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            state = 'unknown'
        if not configured:
            state = 'not_configured'
        elif guard['status'] != 'ok':
            state = 'unknown'
        elif guard['percent'] == 0 and state == 'ready':
            state = 'blocked'
        return {'state': state, 'blocked': state != 'ready', 'automatic_paid_upgrade': False}

    rows = []
    for identity, platform, service, meter, configured, names, allocation, purpose, reset_label in (
        ('cloudflare-gemma', 'Cloudflare Workers Free', 'Gemma 對話及 Whisper 語音輸入',
         'cloudflare_gemma_neuron_reservations', bool(cloudflare_gemma.configuration()),
         ('cloudflare-gemma-quota-stop.json', 'cloudflare-gemma-cooldown.json'),
         '方案列示每日 10,000 Neurons；官方剩餘未回傳。',
         '理解居民需要、自然聊天、延續本輪上下文，以及辨識廣東話錄音；兩項服務共用此每日額度，不轉用其他模型。',
         '方案按 UTC 每日重設；下方時間屬系統保守守護，並非官方餘額查詢結果。'),
        ('azure-voice', 'Microsoft Azure Speech · Free F0', '廣東話語音（曉曼）',
         'azure_tts_characters', azure_voice.configured(), ('azure-voice-control.json',),
         'F0 方案列示每月 500,000 計費字元；官方剩餘未回傳。',
         '將數字人回覆朗讀成香港廣東話；沒有本機聲線或付費備援。',
         '官方按月計算；資源精確重設日期未取得。')):
        protected = guard(meter)
        rows.append({'id': identity, 'platform': platform, 'service': service, 'active': True,
            'provider': {'used': None, 'limit': None, 'remaining': None, 'percent': None,
                         'reset_at': None, 'status': 'not_reported' if configured else 'not_configured',
                         'source': 'not_reported', 'allocation': allocation},
            'guard': protected, 'purpose': purpose, 'reset_label': reset_label,
            'operation': operation(names, protected, configured),
            'note': '永久資料庫保留的保守預留計數；失敗請求也可能已扣額，不能當官方實際用量。'})
    return rows


def search_rows(snapshot):
    status = snapshot.get('status')
    status = status if status in ('ok', 'stale', 'unavailable', 'not_configured') else 'unavailable'
    data = snapshot.get('data') or {}
    if status in ('ok', 'stale'):
        try:
            stamp = datetime.now(UTC)
            observed_ms = snapshot['updated_at_ms']
            if type(observed_ms) is not int or observed_ms < 0:
                raise ValueError('invalid_observation')
            observed = datetime.fromtimestamp(observed_ms / 1000, UTC)
            if (observed > stamp + timedelta(seconds=60)
                    or (status == 'stale' and (observed.year, observed.month) != (stamp.year, stamp.month))):
                raise ValueError('quota_observation_period_changed')
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            status, data = 'unavailable', {}
    provider = {**counter(data.get('used'), data.get('limit')), 'status': status,
                'updated_at_ms': snapshot.get('updated_at_ms'), 'source': 'tavily_usage_api',
                'unit': 'credits', 'reset_at': None}
    row = {'id': 'tavily', 'platform': 'Tavily', 'service': '網上搜尋', 'active': True,
           'provider': provider, 'guard': None,
           'purpose': '居民詢問最新或屋苑資料未涵蓋的公開資訊時搜尋資料。',
           'note': '直接讀官方 usage API；更新失敗只標示上次記錄，不推算最新餘額。',
           'reset_label': '官方每月 1 號重設；未提供時區及精確時刻。'}
    rows = [row]
    if type(data.get('key_limit')) is int and data['key_limit'] > 0:
        rows.append({**row, 'id': 'tavily-key', 'service': '網上搜尋 · 此 key 上限',
            'provider': {**provider, **counter(data.get('key_used'), data['key_limit'])},
            'purpose': '帳戶餘額與這個 key 上限同時生效，兩者不能相加。',
            'reset_label': '平台未提供此 key 上限的重設日期。'})
    return rows


class CloudQuotas:
    def __init__(self, client_provider):
        self.client_provider = client_provider
        self.reader = QuotaReader(key_provider=lambda: search_key(), fetcher=self.fetch)

    async def fetch(self, key):
        # The staff's Google bearer is never forwarded; only the configured
        # Tavily credential goes to this fixed URL. No automatic redirects.
        try:
            async with asyncio.timeout(QUOTA_DEADLINE):
                async with self.client_provider().stream('GET', 'https://api.tavily.com/usage',
                        headers={'Authorization': 'Bearer ' + key}, timeout=5, follow_redirects=False) as response:
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 65_536:
                            raise ValueError('quota_response_too_large')
                    return json.loads(data)
        except TimeoutError:
            raise httpx.TimeoutException('quota_temporarily_unavailable') from None


def quota_router(authorize, quotas):
    router = APIRouter()

    @router.get(QUOTA_PATH)
    async def quota(request: Request):
        authorize()
        if request.query_params:
            raise HTTPException(400, '用量會自動更新，毋須強制重新查詢。')
        rows = await run_in_threadpool(local_overview)
        rows.extend(search_rows(await quotas.reader.snapshot()))
        return JSONResponse({'scope': 'cloud_candidate', 'public_ready': False, 'overview': {
            'rows': rows, 'active_rows': rows, 'other_rows': [], 'capacity_summary': '',
            'updated_at_ms': int(datetime.now(UTC).timestamp() * 1000),
            'local_functions': '屋苑資料、個案進度及明確記憶由永久資料庫處理；雲端語音輸入仍待驗證。',
            'explanation': '官方餘額與系統保守守護分開顯示；未取得數字時不估算百分比。'}},
            headers={'Cache-Control': 'no-store'})

    return router
