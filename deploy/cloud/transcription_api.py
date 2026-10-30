"""Opt-in cloud-only Cantonese ASR; local SenseVoice is unchanged.

Only a bounded 16 kHz PCM WAV is accepted. No URLs, uploads, audio files,
translation, retries, or paid fallback. Reservations share Gemma's existing
8,000-Neuron guard; the patrol reserve retains its separate 2,000 headroom.
Runtime dedup lasts two minutes, not across process restarts. Failed attempts
remain charged and cannot be retried automatically with a replacement ID.
"""
import asyncio
import base64
import hashlib
import json
import math
import re
import sqlite3
import struct
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from edge_hub import cloudflare_gemma
from edge_hub.cloud_allowance import AllowanceExceeded, CloudAllowance
from edge_hub.control_state import read_control, write_control
from edge_hub.event_request import EventBodyLimitMiddleware
from edge_hub.storage_context import current_storage

PATH = '/api/v1/resident/transcription'
MODEL = '@cf/openai/whisper-large-v3-turbo'
MAX_AUDIO = 44 + 45 * 32000
MAX_BASE64 = 4 * math.ceil(MAX_AUDIO / 3)
DEADLINE = 15


class CloudTranscriptionBodyLimit(EventBodyLimitMiddleware):
    label = 'resident transcription'

    def __init__(self, app):
        # Fixed, cloud-route-only ceiling for 45 seconds of base64 WAV. The
        # original middleware's 1 MiB constructor ceiling/native defaults stay.
        self.app, self.max_bytes, self.timeout, self.max_depth = app, 2 * 1024 * 1024, 15., 8

    def matches(self, scope):
        return scope['type'] == 'http' and scope.get('method') == 'POST' and scope.get('path') == PATH


class AudioInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    session_id: str = Field(pattern='^[a-f0-9]{32}$')
    input_id: str = Field(pattern='^[a-f0-9]{32}$')
    audio: str = Field(min_length=60, max_length=MAX_BASE64)


def wav_data(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not 44 + 8000 <= len(raw) <= MAX_AUDIO:
            raise ValueError('invalid')
        if (raw[:4] != b'RIFF' or raw[8:16] != b'WAVEfmt ' or raw[36:40] != b'data'
                or struct.unpack_from('<I', raw, 4)[0] != len(raw) - 8
                or struct.unpack_from('<IHHIIHH', raw, 16) != (16, 1, 1, 16000, 32000, 2, 16)
                or struct.unpack_from('<I', raw, 40)[0] != len(raw) - 44 or (len(raw) - 44) % 2):
            raise ValueError('invalid')
        return raw
    except (ValueError, TypeError, struct.error):
        raise HTTPException(400, '請重新講一次；這段錄音格式或長度未能接納。') from None


def ready():
    storage = current_storage()
    if storage is None:
        raise HTTPException(503, '雲端語音輸入尚未啟用。')
    root = storage.settings_root
    try:
        config = json.loads((root / 'cloudflare-whisper-free.json').read_text(encoding='utf-8'))
        if config != {'enabled': True, 'user_approved': True, 'model': MODEL, 'plan': 'Free'}:
            raise ValueError('not_approved')
        info = cloudflare_gemma.configuration()
        if not info or not re.fullmatch('[0-9a-f]{32}', info.get('account_id', '')):
            raise ValueError('not_configured')
        if cloudflare_gemma.cooling():
            raise ValueError('cooling')
        stopped = read_control(root, 'cloudflare-gemma-quota-stop.json')
        if stopped is not None and datetime.now(UTC) < datetime.fromisoformat(stopped['until']):
            raise ValueError('quota_stopped')
        return info, root
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        raise HTTPException(503, '雲端語音輸入暫時未能使用，請先用文字。') from None


class Transcription:
    def __init__(self, client):
        self.client = client
        self.client_override = None
        self.entries = OrderedDict()
        self.closed = False

    async def close(self):
        self.closed = True
        # Finish bounded work before closing storage/clients. No abandoned
        # reservation thread and no claim that upstream work was rolled back.
        await asyncio.gather(*(item['task'] for item in self.entries.values()), return_exceptions=True)
        self.entries.clear()

    async def transcribe(self, payload, principal):
        raw = wav_data(payload.audio)
        if not any(raw[44:]):
            return {'text': '', 'engine': 'cloudflare-whisper-free', 'model': MODEL}
        if self.closed:
            raise HTTPException(503, '語音服務暫時未能使用。')
        info, root = await run_in_threadpool(ready)
        key = (principal.subject, payload.session_id, payload.input_id)
        digest = hashlib.sha256(raw).digest()
        for old, item in list(self.entries.items()):
            if item['task'].done() and time.monotonic() - item['started'] > 120:
                del self.entries[old]
        if key in self.entries:
            item = self.entries[key]
            if item['digest'] != digest:
                raise HTTPException(409, '同一次錄音的內容已改變，未有重新送出。')
        else:
            if sum(not item['task'].done() for item in self.entries.values()) >= 2:
                raise HTTPException(429, '正在處理語音，請稍候再講。')
            if len(self.entries) >= 32:
                for old, item in self.entries.items():
                    if item['task'].done():
                        del self.entries[old]
                        break
            task = asyncio.create_task(self.dispatch(raw, info, root))
            # Consume failures even if every browser disconnects. The original
            # task retains the failure for a duplicate request in this runtime.
            task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
            item = self.entries[key] = {'task': task, 'digest': digest, 'started': time.monotonic()}
        return await asyncio.shield(item['task'])

    async def dispatch(self, raw, info, root):
        # 46.63 Neurons/min official rate, 10% conservative headroom; duration
        # comes from verified PCM bytes, never a caller's claimed duration.
        neurons = max(1, math.ceil((len(raw) - 44) / 32000 / 60 * 46.63 * 1.1))
        def reserve():
            key = cloudflare_gemma._crypt((root / 'cloudflare-gemma-key.dpapi').read_bytes(), decrypt=True)
            if (not isinstance(key, bytes) or not 16 <= len(key) <= 4096 or not key.isascii()
                    or any(value <= 32 or value == 127 for value in key)):
                raise ValueError('credential_unavailable')
            CloudAllowance(root / 'cloud-usage.sqlite3').reserve({'cloudflare_gemma_neuron_reservations': neurons})
            return key.decode('ascii')
        try:
            secret = await run_in_threadpool(reserve)
        except AllowanceExceeded:
            raise HTTPException(429, '今日免費服務額度已到上限，未有送出錄音。') from None
        except (OSError, ValueError, RuntimeError, LookupError, sqlite3.Error):
            raise HTTPException(503, '未能確認免費額度，錄音尚未送出。') from None
        client = self.client_override or self.client()
        status = None
        try:
            async with asyncio.timeout(DEADLINE):
                async with client.stream('POST',
                    f'https://api.cloudflare.com/client/v4/accounts/{info["account_id"]}/ai/run/{MODEL}',
                    headers={'Authorization': 'Bearer ' + secret}, timeout=DEADLINE,
                    json={'audio': base64.b64encode(raw).decode('ascii'), 'task': 'transcribe', 'language': 'yue',
                          'initial_prompt': '香港廣東話，使用繁體中文。按原話轉錄，不要翻譯或補充。',
                          'condition_on_previous_text': False}) as response:
                    status = response.status_code
                    if status != 200:
                        raise ValueError('provider_unavailable')
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > 65536:
                            raise ValueError('oversized_response')
                        data.extend(chunk)
                    answer = json.loads(data)
                    result = answer.get('result') if isinstance(answer, dict) else None
                    if answer.get('success') is not True or not isinstance(result, dict) or answer.get('errors'):
                        raise ValueError('invalid_response')
                    text = result.get('text')
                    if text is None and isinstance(result.get('transcription_info'), dict):
                        text = result['transcription_info'].get('text')
                    if (not isinstance(text, str) or len(text) > 4000 or '\x00' in text
                            or any(0xD800 <= ord(char) <= 0xDFFF for char in text)):
                        raise ValueError('invalid_transcription')
                    return {'text': text.strip(), 'engine': 'cloudflare-whisper-free', 'model': MODEL}
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError, AttributeError):
            if status in (402, 429):
                await run_in_threadpool(write_control, root, 'cloudflare-gemma-cooldown.json', {
                    'until': (datetime.now(UTC) + timedelta(seconds=300)).isoformat(), 'reason': 'rate_limit'})
                raise HTTPException(429, '免費語音服務暫時到達流量上限，請先用文字。') from None
            raise HTTPException(503, '未能確認這段錄音的辨識結果，請先用文字；沒有自動重送。') from None


def transcription_router(engine, principal):
    router = APIRouter()

    @router.post(PATH)
    async def transcribe(payload: AudioInput, _request: Request):
        identity = principal()
        if identity is None:
            raise HTTPException(401)
        return await engine.transcribe(payload, identity)

    return router
