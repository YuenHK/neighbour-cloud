"""Provider-reported search credits, separate from local fallback guard counters."""
import asyncio
import hashlib
import time
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from edge_hub.cloud_allowance import LIMITS
from edge_hub.cloud_credentials import settings_root
from edge_hub.estate_services import search_key
from edge_hub.usage_snapshot import usage_snapshot


def nonnegative(value):
    return value if type(value) is int and value >= 0 else None


def normalize_usage(payload):
    account = payload.get('account', {})
    key = payload.get('key', {})
    used, limit = nonnegative(account.get('plan_usage')), nonnegative(account.get('plan_limit'))
    key_used, key_limit = nonnegative(key.get('usage')), nonnegative(key.get('limit'))
    remaining = max(0, limit-used) if used is not None and limit is not None else None
    key_remaining = max(0, key_limit-key_used) if key_used is not None and key_limit is not None else None
    return {'plan': str(account.get('current_plan', '未提供'))[:80], 'used': used, 'limit': limit,
        'remaining': remaining, 'key_used': key_used, 'key_limit': key_limit, 'key_remaining': key_remaining,
        'effective_remaining': min(remaining, key_remaining) if remaining is not None and key_remaining is not None else remaining,
        'paygo_used': nonnegative(account.get('paygo_usage')), 'paygo_limit': nonnegative(account.get('paygo_limit')),
        'source': 'tavily_usage_api', 'reset_rule': '每月 1 號重設；供應商沒有提供精確重設時間'}


class QuotaReader:
    def __init__(self, *, key_provider=search_key, fetcher=None, clock=time.monotonic):
        self.key_provider = key_provider
        self.fetcher = fetcher or self.fetch
        self.clock = clock
        self.lock = asyncio.Lock()
        self.key_id = None
        self.attempted = float('-inf')
        self.state = None
        self.last_success = None

    @staticmethod
    def normalize(payload):
        data = normalize_usage(payload)
        if data['used'] is None or data['limit'] is None:
            raise ValueError('provider did not report plan counters')
        return data

    @staticmethod
    async def fetch(key):
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.get('https://api.tavily.com/usage', headers={'Authorization': 'Bearer '+key})
            response.raise_for_status()
            return response.json()

    async def snapshot(self, *, refresh=False):
        async with self.lock:
            try:
                key = self.key_provider()
            except (OSError, ValueError, RuntimeError):
                return {'status': 'unavailable', 'data': None}
            identity = hashlib.sha256(key.encode()).digest() if key else None
            if identity != self.key_id:
                self.key_id = identity
                self.state = self.last_success = None
                self.attempted = float('-inf')
            if not key:
                return {'status': 'not_configured', 'data': None}
            if self.state and self.clock()-self.attempted < (5 if refresh else 60):
                return self.state
            self.attempted = self.clock()
            try:
                data = self.normalize(await self.fetcher(key))
                self.last_success = {'data': data, 'updated_at_ms': int(time.time()*1000)}
                self.state = {'status': 'ok', **self.last_success}
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
                self.state = {'status': 'stale' if self.last_success else 'unavailable',
                    **(self.last_success or {'data': None, 'updated_at_ms': None})}
            return self.state


def backup_usage():
    """Local guard counters cannot establish a provider's balance or quota."""
    database = settings_root()/'cloud-usage.sqlite3'
    period = datetime.now(UTC).strftime('%Y-%m-%d')
    meters = ('siliconflow_chat_requests', 'siliconflow_stt_seconds')
    snapshot = usage_snapshot(database, (period,))
    if snapshot is None:
        return {'scope': 'local_guard_only', 'status': 'unavailable', 'items': []}
    values = {meter: amount for (meter, _), amount in snapshot.items()}
    return {'scope': 'local_guard_only', 'status': 'ok', 'period_utc': period,
        'items': [{'meter': meter, 'used': values.get(meter, 0), 'limit': LIMITS[meter][1],
            'remaining': max(0, LIMITS[meter][1]-values.get(meter, 0))} for meter in meters]}


def resident_chat_usage():
    from edge_hub import cloudflare_gemma
    from edge_hub.resident_cloud import state
    from edge_hub.resident_inference import configuration
    from edge_hub.resident_models import FAST_MODEL
    cf_selected = cloudflare_gemma.selected()
    meter = 'cloudflare_gemma_neuron_reservations' if cf_selected else 'gemini_chat_requests'
    database = settings_root()/'cloud-usage.sqlite3'
    period = datetime.now(UTC).strftime('%Y-%m-%d')
    snapshot = usage_snapshot(database, (period,))
    used = snapshot.get((meter, period), 0) if snapshot is not None else None
    return {**state(configuration().get('cloud_model', FAST_MODEL)), 'scope': 'local_guard_only', 'used': used,
            'limit': LIMITS[meter][1], 'meter': meter}


def quota_router(authorize, reader=None, balance_reader=None):
    router = APIRouter()
    from edge_hub.local_resources import resources_router
    router.include_router(resources_router(authorize))
    reader = reader or QuotaReader()

    @router.get('/api/v1/service-desk/quota')
    async def quota(refresh: bool = False, x_operator_key: str | None = Header(default=None)):
        authorize(x_operator_key)
        from edge_hub.gemini_voice import configured
        from edge_hub.quota_overview import overview
        from edge_hub.resident_inference import configuration
        database = settings_root()/'cloud-usage.sqlite3'
        period = datetime.now(UTC).strftime('%Y-%m-%d')
        snapshot = usage_snapshot(database, (period,))
        used = snapshot.get(('gemini_tts_requests', period), 0) if snapshot is not None else None
        tavily = await reader.snapshot(refresh=refresh)
        voice_configured = configured()
        return JSONResponse({'tavily': tavily,
            'overview': overview(tavily, voice_configured=voice_configured),
            'chat': resident_chat_usage(),
            'assistant_mode': configuration()['mode'], 'backup': backup_usage(),
            'voice': {'configured': voice_configured, 'provider_remaining': None,
                      'scope': 'local_guard_only', 'used': used, 'limit': LIMITS['gemini_tts_requests'][1]}}, headers={'Cache-Control': 'no-store'})

    return router
