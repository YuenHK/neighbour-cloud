"""Explicitly enabled Workers Free Gemma transport. No paid models or retries."""
import asyncio
import json
import math
import re
import sqlite3
import time
from datetime import UTC, datetime, timedelta

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from edge_hub.chat_context import resident_history
from edge_hub.chat_gateway import completion_payload
from edge_hub.cloud_allowance import CloudAllowance
from edge_hub.cloud_credentials import _crypt, settings_root
from edge_hub.control_state import read_control, write_control
from edge_hub.outbound_privacy import messages_for_cloud
from edge_hub.resident_models import GEMMA_MODEL
from edge_hub.storage_context import current_storage

MODEL = '@cf/google/gemma-4-26b-a4b-it'
DEADLINE = 12.0
BASE_OUTPUT_TOKENS = 384
INFORMATION_OUTPUT_TOKENS = 768
_busy = False
_until = 0.0
_last = {'last_route': 'not_used', 'last_failure': None, 'last_elapsed_ms': None}


def selected():
    path = settings_root()/'cloudflare-gemma-free.json'
    if not path.exists():
        return False
    try:
        return json.loads(path.read_text(encoding='utf-8')).get('enabled') is not False
    except (OSError, ValueError, AttributeError):
        return True  # A corrupt selected route must not silently switch provider.


def configuration():
    try:
        info = json.loads((settings_root()/'cloudflare-gemma-free.json').read_text(encoding='utf-8'))
        if (info.get('enabled') is True and info.get('plan') == 'Free' and info.get('ui_verified') is True
                and re.fullmatch('[0-9a-f]{32}', info.get('account_id', ''))
                and (settings_root()/'cloudflare-gemma-key.dpapi').is_file()):
            return info
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def cooling():
    if time.monotonic() < _until:
        return True
    if current_storage() is None:
        return False  # Existing native monotonic cooldown remains unchanged.
    try:
        value = read_control(settings_root(), 'cloudflare-gemma-cooldown.json')
        return datetime.now(UTC) < datetime.fromisoformat(value['until'])
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        return True


def state():
    return {'model': GEMMA_MODEL, 'last_model': GEMMA_MODEL if _last['last_route'] == 'gemma-cloudflare-free' else None,
        'provider': 'Cloudflare Workers Free', 'fallback_model': None, 'cooldown': cooling(),
        'provider_remaining': None, **_last}


def reserve(messages, output_tokens=BASE_OUTPUT_TOKENS):
    # Conservative byte-token bound plus chat template overhead; this is a local
    # reservation, not Cloudflare's measured usage. Failed calls stay reserved.
    block = read_control(settings_root(), 'cloudflare-gemma-quota-stop.json')
    if block is not None:
        until = datetime.fromisoformat(block['until'])
        if datetime.now(UTC) < until:
            raise ValueError('cloudflare_daily_allocation_reached')
    tokens = sum(len(item['content'].encode('utf-8')) + 64 for item in messages)
    neurons = math.ceil(1.1 * (tokens * 9091 + output_tokens * 27273) / 1_000_000)
    CloudAllowance(settings_root()/'cloud-usage.sqlite3').reserve({'cloudflare_gemma_neuron_reservations': neurons})


async def complete(payload, *, prompt, context='', client=None):
    global _busy, _last
    from edge_hub.resident_cloud import CloudUnavailable
    from edge_hub.resident_stream import packet
    info = configuration()
    history = resident_history(payload)
    if not info or not history or history[-1]['role'] != 'user' or len(context) > 8000:
        raise CloudUnavailable('cloudflare_not_ready')
    start = time.monotonic()
    deadline = start + DEADLINE
    while _busy and time.monotonic() < deadline:
        await asyncio.sleep(.025)
    if _busy or cooling():
        raise CloudUnavailable('cloudflare_busy_or_cooling')
    _busy = True
    owned = client is None
    client = client or httpx.AsyncClient(trust_env=False, follow_redirects=False)
    response = None
    closed = False
    output_tokens = INFORMATION_OUTPUT_TOKENS if '本輪是一般資訊查詢' in prompt else BASE_OUTPUT_TOKENS
    progress = {'content_chars': 0, 'reasoning_chars': 0, 'finish_reason': None}

    async def close():
        nonlocal closed
        global _busy
        if closed:
            return
        closed = True
        try:
            if response is not None:
                await response.aclose()
            if owned:
                await client.aclose()
        finally:
            _busy = False

    def failed(error):
        global _until, _last
        status = response.status_code if response is not None else None
        # A per-turn generation/parsing failure is not a provider-wide outage.
        # Never trap all later resident messages behind a false global cooldown.
        semantic = status == 200 and isinstance(error, (ValueError, TypeError, KeyError))
        delay = 0 if semantic else 300 if status in (402, 429) else 60
        _until = time.monotonic() + delay
        persistence_failed = False
        if delay and current_storage() is not None:
            try:
                write_control(settings_root(), 'cloudflare-gemma-cooldown.json', {
                    'until': (datetime.now(UTC) + timedelta(seconds=delay)).isoformat(),
                    'reason': 'rate_limit' if status in (402, 429) else 'network'})
            except (OSError, ValueError, TypeError, sqlite3.Error):
                persistence_failed = True
        _last = {'last_route': 'gemma-cloudflare-free', 'last_failure': 'cloudflare_gemma_unavailable',
            'last_elapsed_ms': round((time.monotonic()-start)*1000),
            'last_failure_detail': {'type': type(error).__name__, 'http_status': status,
                                    'output_token_limit': output_tokens, 'retry_after_seconds': delay, **progress}}
        if persistence_failed:
            _last['last_failure_detail']['control_persistence'] = 'unavailable'
        if isinstance(error, ValueError) and str(error) in {'unexpected_format','upstream_stream_error',
                'invalid_candidate','incomplete_answer','oversized_stream','oversized_answer',
                'cloudflare_daily_allocation_reached'}:
            _last['last_failure_detail']['reason'] = str(error)

    async def bounded(value):
        return await asyncio.wait_for(value, max(.001, deadline-time.monotonic()))

    async def sentences():
        total, pending, stopped = 0, '', False
        iterator = response.aiter_lines().__aiter__()
        size = 0
        while True:
            try:
                line = await bounded(anext(iterator))
            except StopAsyncIteration:
                break
            size += len(line)
            if size > 100000:
                raise ValueError('oversized_stream')
            if not line.startswith('data:'):
                continue
            raw = line[5:].strip()
            if raw == '[DONE]':
                break
            if not raw:
                continue
            event = json.loads(raw)
            if event.get('error'):
                raise ValueError('upstream_stream_error')
            choices = event.get('choices', [])
            if not choices and event.get('usage'):
                continue
            if len(choices) != 1:
                raise ValueError('invalid_candidate')
            item = choices[0]
            delta = item.get('delta') or {}
            finish = item.get('finish_reason')
            progress['finish_reason'] = finish if finish in (None, 'stop', 'length', 'tool_calls', 'content_filter') else 'other'
            progress['content_chars'] += len(delta.get('content') or '') if isinstance(delta.get('content'), str) else 0
            progress['reasoning_chars'] += len(delta.get('reasoning_content') or '') if isinstance(delta.get('reasoning_content'), str) else 0
            if delta.get('refusal') or delta.get('tool_calls') or item.get('finish_reason') not in (None, 'stop'):
                raise ValueError('incomplete_answer')
            text = delta.get('content') or ''
            if not isinstance(text, str):
                raise TypeError('invalid_text')
            total += len(text)
            if total > 4000:
                raise ValueError('oversized_answer')
            pending += text
            while match := re.match(r'^[\s\S]*?[。！？!?\n]', pending):
                yield packet(match[0])
                pending = pending[len(match[0]):]
            if item.get('finish_reason') == 'stop':
                stopped = True
                break
        if not stopped or not total:
            raise ValueError('incomplete_answer')
        if pending:
            yield packet(pending)
        _last['last_elapsed_ms'] = round((time.monotonic()-start)*1000)
        yield b'data: [DONE]\n\n'

    iterator = None
    try:
        system = prompt + ('\n本輪已核對資料：\n'+context if context else '')
        system += '\n先用一句簡短完整的廣東話接住問題，以句號結束；再按需要補充，唔好把所有資訊塞成一句。'
        messages = messages_for_cloud([{'role': 'system', 'content': system}, *history])
        if any('已隱去]' in item['content'] for item in messages):
            messages[0]['content'] += '\n方括號內已隱去的欄位只用作資料保護，不要讀出標記、猜測原值或要求居民重講；自然回應其餘需要。'
        reserve(messages, output_tokens)
        key = _crypt((settings_root()/'cloudflare-gemma-key.dpapi').read_bytes(), decrypt=True).decode()
        request = client.build_request('POST',
            f'https://api.cloudflare.com/client/v4/accounts/{info["account_id"]}/ai/v1/chat/completions',
            headers={'Authorization': 'Bearer '+key}, json={
                'model': MODEL, 'messages': messages, 'stream': True, 'max_tokens': output_tokens,
                'temperature': .5, 'chat_template_kwargs': {'enable_thinking': False}, 'store': False},
            timeout=httpx.Timeout(DEADLINE, connect=3, pool=1))
        response = await bounded(client.send(request, stream=True))
        if response.status_code >= 400:
            data = await bounded(response.aread())
            if len(data) <= 10000:
                error = json.loads(data)
                codes = [item.get('code') for item in error.get('errors', [])]
                if 3036 in codes:
                    until = (datetime.now(UTC)+timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                    write_control(settings_root(), 'cloudflare-gemma-quota-stop.json', {'until': until.isoformat()})
        response.raise_for_status()
        if 'text/event-stream' not in response.headers.get('content-type', ''):
            raise ValueError('unexpected_format')
        iterator = sentences()
        first = await bounded(anext(iterator))
    except (httpx.HTTPError, TimeoutError, OSError, ValueError, RuntimeError, TypeError, KeyError, sqlite3.Error) as error:
        failed(error)
        if iterator is not None:
            await iterator.aclose()
        await close()
        raise CloudUnavailable('cloudflare_gemma_unavailable') from None
    except BaseException:
        if iterator is not None:
            await iterator.aclose()
        await close()
        raise
    _last = {'last_route': 'gemma-cloudflare-free', 'last_failure': None, 'last_failure_detail': None,
        'last_elapsed_ms': None}

    async def chunks():
        try:
            yield first
            async for piece in iterator:
                yield piece
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError) as error:
            failed(error)
            yield b'data: {"error":{"code":"resident_stream_incomplete"}}\n\n'
        finally:
            await iterator.aclose()
            await close()

    async def abandoned():
        await iterator.aclose()
        await close()
    headers = {'X-Resident-Model': GEMMA_MODEL, 'X-Resident-Route': 'gemma-cloudflare-free',
        'X-Resident-First-Sentence-Ms': str(round((time.monotonic()-start)*1000))}
    if not payload.get('stream'):
        answer, done = '', False
        async for piece in chunks():
            raw = piece.decode().removeprefix('data:').strip()
            if raw == '[DONE]':
                done = True
            else:
                event = json.loads(raw)
                if event.get('error'):
                    raise CloudUnavailable('cloudflare_stream_incomplete')
                answer += event['choices'][0]['delta']['content']
        if not done:
            raise CloudUnavailable('cloudflare_stream_incomplete')
        return JSONResponse(completion_payload(answer, GEMMA_MODEL), headers=headers)
    return StreamingResponse(chunks(), media_type='text/event-stream', background=BackgroundTask(abandoned), headers=headers)
