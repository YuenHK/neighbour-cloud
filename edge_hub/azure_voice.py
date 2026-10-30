"""Verified F0 HiuMaan only. No billing/upgrade APIs, retries or paid fallback."""
import io
import json
import sqlite3
import time
import unicodedata
import wave
from datetime import UTC, datetime
from xml.sax.saxutils import escape

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from edge_hub.cloud_allowance import LIMITS, CloudAllowance
from edge_hub.cloud_credentials import _crypt, settings_root
from edge_hub.control_state import read_control, write_control
from edge_hub.outbound_privacy import redact
from edge_hub.phase_latency import phase_latency
from edge_hub.usage_snapshot import usage_snapshot

MODEL = 'azure-hiumaan-f0'
VOICE = 'zh-HK-HiuMaanNeural'


def configured():
    try:
        info = json.loads((settings_root()/'azure-speech-f0.json').read_text(encoding='utf-8'))
        return (info.get('sku') == 'F0' and info.get('region') == 'eastasia'
                and (settings_root()/'azure-speech-f0-key.dpapi').is_file())
    except (OSError, ValueError, TypeError):
        return False


def billable_characters(text):
    return sum(2 if unicodedata.name(c, '').startswith(
        ('CJK UNIFIED IDEOGRAPH', 'CJK COMPATIBILITY IDEOGRAPH')) else 1 for c in text)


def status():
    root = settings_root()
    paused = False
    try:
        control = read_control(root, 'azure-voice-control.json')
        if control is not None:
            paused = control['paused']
            if type(paused) is not bool:
                raise ValueError('invalid_control')
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        paused = True  # An unreadable control must never enable synthesis.
    db = root/'cloud-usage.sqlite3'
    period = datetime.now(UTC).strftime('%Y-%m')
    values = usage_snapshot(db, (period,))
    used = values.get(('azure_tts_characters', period), 0) if values is not None else None
    limit = LIMITS['azure_tts_characters'][1]
    return {'configured': configured(), 'paused': paused, 'voice': '曉曼', 'sku': 'F0',
        'used': used, 'limit': limit, 'period_utc': period,
        'remaining': max(0, limit-used) if used is not None else None,
        'blocked': paused or used is None or used >= limit,
        'scope': 'local_guard_only', 'official_monthly_limit': 500000,
        'official_remaining': None, 'automatic_paid_upgrade': False}


def set_paused(paused):
    if type(paused) is not bool:
        raise ValueError('invalid_pause')
    write_control(settings_root(), 'azure-voice-control.json', {'paused': paused})
    return status()  # Never resets usage or changes the resource's SKU.


def require_available():
    current = status()
    if not current['configured'] or current['blocked']:
        raise ValueError('azure_voice_paused_or_limited')


def spoken_private(text):
    text = redact(text)
    for label, spoken in {'電話': '你提供嘅聯絡資料', '電郵': '你提供嘅電郵',
                          '身份證': '私人證件資料', '住戶單位': '你提及嘅單位',
                          '住戶地址': '你提及嘅住址', '居民稱呼': '你'}.items():
        text = text.replace('['+label+'已隱去]', spoken)
    return text


def _audio_chunks(text, *, output_format, client=None):
    """One F0 reservation/request. Consumer must close the generator on cancel."""
    raw = output_format == 'raw-24khz-16bit-mono-pcm'
    if output_format not in ('raw-24khz-16bit-mono-pcm', 'audio-24khz-48kbitrate-mono-mp3'):
        raise ValueError('unsupported_voice_stream_format')
    if not isinstance(text, str) or not 0 < len(text) <= 1500:
        raise ValueError('invalid_voice_input')
    text = spoken_private(text)
    require_available()
    root = settings_root()
    key = _crypt((root/'azure-speech-f0-key.dpapi').read_bytes(), decrypt=True).decode()
    CloudAllowance(root/'cloud-usage.sqlite3').reserve({'azure_tts_characters': billable_characters(text)})
    owned = client is None
    client = client or httpx.Client(timeout=15, trust_env=False, follow_redirects=False)
    started, size, pending = time.monotonic(), 0, b''
    try:
        with client.stream('POST', 'https://eastasia.tts.speech.microsoft.com/cognitiveservices/v1',
            headers={'Ocp-Apim-Subscription-Key': key, 'Content-Type': 'application/ssml+xml',
                     'X-Microsoft-OutputFormat': output_format},
            content=f'<speak version="1.0" xml:lang="zh-HK"><voice name="{VOICE}">{escape(text)}</voice></speak>'.encode(),
            timeout=15) as response:
            response.raise_for_status()
            checked_mp3 = False
            for chunk in response.iter_bytes(chunk_size=4096):
                if time.monotonic()-started > 30:
                    raise ValueError('voice_stream_deadline')
                pending += chunk
                size += len(chunk)
                if size > 5_760_000:
                    raise ValueError('oversized_audio')
                if raw:
                    even = len(pending)//2*2
                    if even:
                        yield pending[:even]
                        pending = pending[even:]
                else:
                    if not checked_mp3:
                        if len(pending) < 3:
                            continue
                        if not (pending.startswith(b'ID3') or pending[0] == 255 and pending[1] & 224 == 224):
                            raise ValueError('invalid_mp3_stream')
                        checked_mp3 = True
                    yield pending
                    pending = b''
            if pending or size == 0:
                raise ValueError('invalid_pcm')
    finally:
        if owned:
            client.close()


def pcm_chunks(text, *, client=None):
    """Existing resident PCM path. No change of voice, reservation or playback."""
    yield from _audio_chunks(text, output_format='raw-24khz-16bit-mono-pcm', client=client)


def mp3_chunks(text, *, client=None):
    """Optional cloud transport, 48 kbit/s mono. Not selected by the current UI.

    At the codec's nominal rate, bandwidth is 8x below raw 24k/16bit mono PCM.
    This is not an end-to-end latency or listening-quality claim.
    """
    yield from _audio_chunks(text, output_format='audio-24khz-48kbitrate-mono-mp3', client=client)


@phase_latency.measure('azure_complete')
def synthesize(text, *, client=None):
    if not isinstance(text, str) or not 0 < len(text) <= 1500:
        raise ValueError('invalid_voice_input')
    text = redact(text)
    for label, spoken in {'電話': '你提供嘅聯絡資料', '電郵': '你提供嘅電郵',
                          '身份證': '私人證件資料', '住戶單位': '你提及嘅單位',
                          '住戶地址': '你提及嘅住址', '居民稱呼': '你'}.items():
        text = text.replace('['+label+'已隱去]', spoken)
    require_available()
    root = settings_root()
    key = _crypt((root/'azure-speech-f0-key.dpapi').read_bytes(), decrypt=True).decode()
    CloudAllowance(root/'cloud-usage.sqlite3').reserve({'azure_tts_characters': billable_characters(text)})
    owned = client is None
    client = client or httpx.Client(timeout=15, trust_env=False, follow_redirects=False)
    try:
        response = client.post('https://eastasia.tts.speech.microsoft.com/cognitiveservices/v1',
            headers={'Ocp-Apim-Subscription-Key': key, 'Content-Type': 'application/ssml+xml',
                     'X-Microsoft-OutputFormat': 'riff-24khz-16bit-mono-pcm'},
            content=f'<speak version="1.0" xml:lang="zh-HK"><voice name="{VOICE}">{escape(text)}</voice></speak>'.encode(),
            timeout=15)
        response.raise_for_status()
        data = response.content
        if len(data) > 6_000_000:
            raise ValueError('oversized_audio')
        with wave.open(io.BytesIO(data), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000) or not 0 < wav.getnframes()/24000 <= 120:
                raise ValueError('invalid_audio')
        return data
    finally:
        if owned:
            client.close()


def control_router(authorize):
    router = APIRouter()

    class Pause(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        paused: bool

    @router.get('/api/v1/service-desk/voice-control')
    def read(x_operator_key: str | None = Header(default=None)):
        authorize(x_operator_key)
        return status()

    @router.put('/api/v1/service-desk/voice-control')
    def update(body: Pause, x_operator_key: str | None = Header(default=None)):
        authorize(x_operator_key)
        try:
            return set_paused(body.paused)
        except (OSError, sqlite3.Error):
            raise HTTPException(503, '未能儲存語音開關，請稍後再試。') from None

    return router
