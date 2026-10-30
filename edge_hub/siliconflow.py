"""Opt-in free-model routing. No paid models, image uploads or automatic retries."""
from __future__ import annotations

import math
from typing import Any

import httpx
from fastapi import HTTPException

from edge_hub.cloud_allowance import AllowanceExceeded, CloudAllowance
from edge_hub.cloud_credentials import settings_root, siliconflow_key
from edge_hub.service_identity import SERVICE_SYSTEM_PROMPT

API_BASE = 'https://api.siliconflow.cn/v1'
CHAT_MODEL = 'XingChenAGI/Xing4.0-29B'
STT_MODEL = 'FunAudioLLM/SenseVoiceSmall'


def reserve(amounts: dict[str, float]) -> None:
    try:
        CloudAllowance(settings_root() / 'cloud-usage.sqlite3').reserve(amounts)
    except AllowanceExceeded as exc:
        raise HTTPException(429, '已達本機硅基流動每日用量上限') from exc


def chat_payload(question: str, *, stream: bool, history=None, style='voice', service_context='') -> dict[str, Any]:
    if not question.strip() or len(question) > 4000:
        raise HTTPException(400, '對話文字須為 1–4000 字元')
    from edge_hub.chat_context import bounded_history
    safe_history = bounded_history({'messages': history if history is not None else
                                    [{'role': 'user', 'content': question}]})
    return {
        'model': CHAT_MODEL,
        'messages': [
            {'role': 'system', 'content': SERVICE_SYSTEM_PROMPT + service_context + '用自然香港廣東話、'
             '繁體中文回答，參考前面對話理解追問。' +
             ('最多兩句，每句盡量十五至二十五字，方便即時語音播放。' if style == 'voice' else
              '文字問題可按需要解釋，不要只作一句敷衍回答。') +
             '直接回答，不輸出思考過程、ACT 或工具指令。'
             '你不能控制機械人馬達或解除停止。'},
            *safe_history,
        ],
        'stream': stream, 'temperature': 0.3, 'max_tokens': 160 if style == 'voice' else 512,
        'enable_thinking': False,
    }


async def transcribe(wav: bytes, seconds: float, *, client: httpx.AsyncClient | None = None) -> str:
    if not math.isfinite(seconds) or not 0 < seconds <= 45 or len(wav) > 1500000:
        raise HTTPException(400, '每段語音須在 45 秒內')
    key = siliconflow_key()
    reserve({'siliconflow_stt_seconds': math.ceil(seconds)})
    async def upload(connection):
        return await connection.post(
            API_BASE + '/audio/transcriptions',
            headers={'Authorization': 'Bearer ' + key},
            data={'model': STT_MODEL}, files={'file': ('speech.wav', wav, 'audio/wav')},
        )

    try:
        if client is not None:
            response = await upload(client)
        else:
            async with httpx.AsyncClient(timeout=25, follow_redirects=False) as connection:
                response = await upload(connection)
    except httpx.HTTPError as exc:
        raise HTTPException(503, '硅基流動辨識暫時無法連線') from exc
    if response.status_code != 200:
        raise HTTPException(503, f'硅基流動辨識未成功（HTTP {response.status_code}）')
    try:
        text = response.json()['text']
        if not isinstance(text, str):
            raise TypeError('Invalid text')
        return text.strip()
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(502, '語音辨識回傳格式無效') from exc
