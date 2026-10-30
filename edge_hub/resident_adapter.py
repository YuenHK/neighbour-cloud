"""AIRI-selectable adapter for the current free Gemma deployment.

Other providers are selected by AIRI itself, never inferred or failed over here.
"""
import json

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from edge_hub.phase_latency import phase_latency
from edge_hub.resident_cloud import CloudUnavailable, complete
from edge_hub.resident_models import GEMMA_MODEL
from edge_hub.resident_replay import TurnReplay
from edge_hub.service_desk import local_resident_request


def native_stream(response):
    async def chunks():
        done = False
        try:
            async for piece in response.body_iterator:
                text = piece.decode() if isinstance(piece, bytes) else piece
                for line in text.splitlines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        done = True
                        yield b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
                        yield b'data: [DONE]\n\n'
                        return
                    data = json.loads(raw)
                    if data.get('error'):
                        raise ValueError('source_incomplete')
                    yield ('data: '+json.dumps(data, ensure_ascii=False)+'\n\n').encode()
        except (ValueError, TypeError, httpx.HTTPError):
            pass
        finally:
            await response.body_iterator.aclose()
        if not done:
            # xsAI reacts to OpenAI refusal deltas, not a private SSE error
            # object. Never let a partial reply be committed as complete.
            yield b'data: {"choices":[{"index":0,"delta":{"refusal":"resident_stream_incomplete"}}]}\n\n'
    return StreamingResponse(chunks(), headers=dict(response.headers), background=response.background)


def resident_adapter_router(*, resident_request=None, completion=None):
    if ((resident_request is not None and not callable(resident_request))
            or (completion is not None and not callable(completion))):
        raise TypeError('explicit_resident_adapter_dependencies_required')
    router = APIRouter(prefix='/api/v1/resident/model/v1')
    replay = TurnReplay()

    @router.get('/models')
    def models():
        return {'object': 'list', 'data': [{'id': GEMMA_MODEL, 'object': 'model', 'owned_by': 'google'}]}

    @router.post('/chat/completions')
    async def chat(payload: dict, request: Request):
        if not (local_resident_request if resident_request is None else resident_request)(request):
            raise HTTPException(403, '請使用本機服務台。')
        if payload.get('model') != GEMMA_MODEL or payload.get('tools'):
            raise HTTPException(400, '此連接只提供免費 Gemma，其他供應商請在 AIRI 設定。')
        messages = payload.get('messages')
        if not isinstance(messages, list) or not 1 <= len(messages) <= 65:
            raise HTTPException(400, '對話格式不正確。')
        if any(not isinstance(item, dict) or not isinstance(item.get('content'), str) for item in messages):
            raise HTTPException(400, '只接受文字對話。')
        prompt = '\n'.join(item['content'] for item in messages if item.get('role') == 'system')
        if len(prompt) > 14000:
            raise HTTPException(400, '角色設定及本輪資料太長，請縮短後再試。')
        turn_key = replay.key(request.headers, payload)
        cached = replay.begin(turn_key)
        if cached is not None:
            return cached
        try:
            with phase_latency.measure('gemma_response_ready'):
                response = await (complete if completion is None else completion)(
                    {**payload, '_gemma_only': True, '_sentence_stream': True},
                    prompt=prompt, context='',
                    client=getattr(request.app.state, 'resident_cloud_client', None), model=GEMMA_MODEL)
        except CloudUnavailable:
            replay.pending.discard(turn_key)
            raise HTTPException(503, 'Gemma 暫時未能回覆，未切換其他模型。') from None
        except BaseException:
            replay.pending.discard(turn_key)
            raise
        response.headers['Cache-Control'] = 'no-store'
        result = native_stream(response) if isinstance(response, StreamingResponse) else response
        return replay.wrap(turn_key, result)

    return router
