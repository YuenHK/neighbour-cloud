import asyncio
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from edge_hub import resident_adapter
from edge_hub.resident_cloud import CloudUnavailable
from edge_hub.resident_models import GEMMA_MODEL


def test_native_adapter_supplies_finish_packet_and_turns_late_failure_into_sdk_error():
    async def run(fail):
        async def source():
            yield b'data: {"choices":[{"delta":{"content":"public sentence"}}]}\n\n'
            yield b'data: {"error":{"code":"incomplete"}}\n\n' if fail else b'data: [DONE]\n\n'
        response = resident_adapter.native_stream(StreamingResponse(source()))
        return b''.join([piece async for piece in response.body_iterator])
    complete = asyncio.run(run(False))
    assert b'"finish_reason":"stop"' in complete and complete.count(b'[DONE]') == 1
    failed = asyncio.run(run(True))
    assert b'"refusal":"resident_stream_incomplete"' in failed and b'[DONE]' not in failed


def test_airi_gemma_adapter_lists_only_free_model_and_honors_native_persona(monkeypatch):
    complete = AsyncMock(return_value=JSONResponse({'ok': True}))
    monkeypatch.setattr(resident_adapter, 'complete', complete)
    app = FastAPI()
    app.include_router(resident_adapter.resident_adapter_router())
    with TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 1)) as client:
        base = '/api/v1/resident/model/v1'
        assert client.get(base+'/models').json()['data'][0]['id'] == GEMMA_MODEL
        body = {'model': GEMMA_MODEL, 'messages': [{'role': 'system', 'content': 'AIRI測試角色：親切鄰居'}, {'role': 'user', 'content': '公開測試'}]}
        assert client.post(base+'/chat/completions', json=body).status_code == 200
        assert 'AIRI測試角色' in complete.call_args.kwargs['prompt']
        assert complete.call_args.args[0]['_gemma_only']
        assert client.post(base+'/chat/completions', json={**body, 'model': 'paid-model'}).status_code == 400
        assert client.post(base+'/chat/completions', json={**body, 'tools': [{'name': 'move_robot'}]}).status_code == 400
        complete.side_effect = CloudUnavailable('synthetic')
        assert client.post(base+'/chat/completions', json=body).status_code == 503
        assert complete.await_count == 2
