from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from edge_hub import siliconflow
from edge_hub.chat_context import bounded_history, response_style
from edge_hub.cloud_credentials import siliconflow_enabled, siliconflow_key
from edge_hub.faq import OfflineFaq
from edge_hub.service_identity import SERVICE_SYSTEM_PROMPT

OLLAMA_OPENAI_BASE = "http://127.0.0.1:11434/v1"
MODELSCOPE_OPENAI_BASE = "https://api-inference.modelscope.cn/v1"
DEFAULT_MODELSCOPE_MODEL = "Qwen/Qwen3.5-35B-A3B"
DEFAULT_CLOUD_TIMEOUT_SECONDS = 10.0
LOCAL_FALLBACK_MODEL = 'qwen3:1.7b'
LOCAL_SYSTEM_PROMPT = (
    SERVICE_SYSTEM_PROMPT +
    "只輸出給使用者閱讀的文字，不要輸出 ACT、工具調用、特殊標記或思考過程。"
    "參考前面對話回答追問，不知道就說不知道。你不能控制機械人、解除停止或啟用聲畫。"
)


def modelscope_token() -> str:
    token = os.environ.get("MODELSCOPE_ACCESS_TOKEN", "").strip()
    if token:
        return token
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        return ""
    token_path = Path(local_app_data) / "ZhiweiJianbing" / "modelscope-token.txt"
    try:
        return token_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def cloud_enabled() -> bool:
    return os.environ.get("ZHIWEI_LLM_PROVIDER", "auto").lower() != "local" and bool(
        modelscope_token()
    )


def latest_user_text(payload: dict[str, Any]) -> str:
    for message in reversed(payload.get("messages", [])):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return " ".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
    return ""


def completion_payload(answer: str, model: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-faq-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def local_chat_payload(payload: dict[str, Any], *, service_context='') -> dict[str, Any]:
    """Build a small-model-safe request without AIRI action/tool instructions."""
    history = bounded_history(payload)
    if not history:
        raise HTTPException(400, 'conversation requires user text')
    history[-1] = {**history[-1], 'content': history[-1]['content'] + '\n/no_think'}
    voice = response_style(payload) == 'voice'
    local_payload = {'model': payload.get('model', LOCAL_FALLBACK_MODEL),
                     'stream': bool(payload.get('stream', False)),
                     'messages': [{'role': 'system', 'content': LOCAL_SYSTEM_PROMPT + service_context +
                         ('請簡短回答，最多兩句。' if voice else '請按問題需要解釋，避免無關贅述。')}, *history],
                     'temperature': .3, 'max_tokens': 128 if voice else 384}
    return local_payload


async def faq_stream(answer: str, model: str) -> AsyncIterator[bytes]:
    completion_id = f"chatcmpl-faq-{uuid.uuid4().hex}"
    chunks = [
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": answer},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]
    for chunk in chunks:
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
    yield b"data: [DONE]\n\n"


async def proxy_openai(
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    *,
    base_url: str,
    timeout: float,
    token: str = "",
    client: httpx.AsyncClient | None = None,
):
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=False,
                                   trust_env=base_url != OLLAMA_OPENAI_BASE)
    headers = {"Authorization": f"Bearer {token}"} if token else None
    request = client.build_request(
        method, f"{base_url}/{path}", json=payload, headers=headers, timeout=timeout
    )
    try:
        response = await client.send(request, stream=True)
    except Exception:
        if owns_client:
            await client.aclose()
        raise
    if response.status_code >= 400:
        content = await response.aread()
        await response.aclose()
        if owns_client:
            await client.aclose()
        detail = (f'硅基流動請求失敗（HTTP {response.status_code}）'
                  if base_url == siliconflow.API_BASE else content.decode(errors="replace"))
        raise HTTPException(response.status_code, detail)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            if owns_client:
                await client.aclose()

    return StreamingResponse(
        body(),
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/json"),
    )


async def proxy_to_ollama(method: str, path: str, payload: dict[str, Any] | None = None):
    return await proxy_openai(
        method,
        path,
        payload,
        base_url=OLLAMA_OPENAI_BASE,
        timeout=120,
    )


async def proxy_to_modelscope(payload: dict[str, Any], *, client: httpx.AsyncClient | None = None):
    cloud_payload = dict(payload)
    cloud_payload["model"] = os.environ.get(
        "MODELSCOPE_MODEL", DEFAULT_MODELSCOPE_MODEL
    )
    timeout = float(
        os.environ.get("MODELSCOPE_TIMEOUT_SECONDS", DEFAULT_CLOUD_TIMEOUT_SECONDS)
    )
    return await proxy_openai(
        "POST",
        "chat/completions",
        cloud_payload,
        base_url=MODELSCOPE_OPENAI_BASE,
        timeout=timeout,
        token=modelscope_token(),
        **({'client': client} if client is not None else {}),
    )


async def local_chat_fallback(payload: dict[str, Any], reason: str, *, service_context=''):
    # Only bounded user/assistant text is forwarded. Never pass cloud model IDs,
    # images, cloud credentials or AIRI tool/action instructions to Ollama.
    local_payload = local_chat_payload(payload, service_context=service_context)
    local_payload['model'] = LOCAL_FALLBACK_MODEL
    try:
        response = await proxy_to_ollama('POST', 'chat/completions', local_payload)
    except (httpx.HTTPError, HTTPException) as error:
        raise HTTPException(503, '雲端對話暫時不可用，本機備援亦未能回覆；請保留輸入稍後再試') from error
    response.headers['X-Zhiwei-Chat-Route'] = 'ollama-fallback'
    response.headers['X-Zhiwei-Cloud-Result'] = reason
    return response


async def route_chat(payload: dict[str, Any], faq: OfflineFaq, *, cloud_client: httpx.AsyncClient | None = None, service_context=''):
    history = bounded_history(payload)
    payload = {**payload, 'messages': history}
    question = latest_user_text(payload)
    if question and not service_context:
        result = faq.query(question)
        if result.matched and result.source_id != 'mental-health':
            model = str(payload.get("model", "offline-faq"))
            if payload.get("stream", False):
                return StreamingResponse(faq_stream(result.answer, model), media_type="text/event-stream")
            return JSONResponse(completion_payload(result.answer, model))

    if siliconflow_enabled():
        cloud_payload = siliconflow.chat_payload(question, stream=bool(payload.get('stream', False)),
                                                history=history, style=response_style(payload), service_context=service_context)
        token = siliconflow_key()
        try:
            siliconflow.reserve({'siliconflow_chat_requests': 1,
                                 'siliconflow_input_characters': sum(len(m['content']) for m in history)})
            return await proxy_openai('POST', 'chat/completions', cloud_payload,
                                      base_url=siliconflow.API_BASE, timeout=25, token=token,
                                      **({'client': cloud_client} if cloud_client is not None else {}))
        except httpx.HTTPError:
            return await local_chat_fallback(payload, 'network-error', service_context=service_context)
        except HTTPException as error:
            if error.status_code != 429 and not 500 <= error.status_code <= 599:
                raise
            # This branch returns directly: no ModelScope/other cloud and no
            # repeated cloud request. Stream-body failures after a response was
            # returned are deliberately not replayed via another provider.
            return await local_chat_fallback(payload, f'http-{error.status_code}', service_context=service_context)

    if cloud_enabled():
        try:
            return await proxy_to_modelscope(local_chat_payload(payload, service_context=service_context),
                **({'client': cloud_client} if cloud_client is not None else {}))
        except (httpx.HTTPError, HTTPException, ValueError):
            # 免費服務可能排隊、限流或暫停；本機模型永遠保留作安全回退。
            pass

    return await proxy_to_ollama(
        "POST", "chat/completions", local_chat_payload(payload, service_context=service_context)
    )
