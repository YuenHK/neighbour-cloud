import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from edge_hub import chat_gateway, siliconflow
from edge_hub.faq import OfflineFaq


def test_shared_resident_transport_stays_open_after_each_stream_and_error():
    async def scenario():
        responses = []
        def respond(request):
            response = httpx.Response(503 if request.url.path.endswith('failure') else 200,
                content=b'data: [DONE]\n\n', headers={'Content-Type': 'text/event-stream'})
            responses.append(response)
            return response
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            for _ in range(2):
                response = await chat_gateway.proxy_openai('POST', 'chat/completions', {},
                    base_url=siliconflow.API_BASE, timeout=25, client=client)
                assert b''.join([chunk async for chunk in response.body_iterator]) == b'data: [DONE]\n\n'
                assert not client.is_closed and responses[-1].is_closed
            with pytest.raises(HTTPException):
                await chat_gateway.proxy_openai('POST', 'failure', {},
                    base_url=siliconflow.API_BASE, timeout=25, client=client)
            assert not client.is_closed and responses[-1].is_closed
    asyncio.run(scenario())


@pytest.fixture
def route(monkeypatch):
    monkeypatch.setattr(chat_gateway, 'siliconflow_enabled', lambda: True)
    monkeypatch.setattr(chat_gateway, 'siliconflow_key', lambda: 'synthetic-key')
    monkeypatch.setattr(siliconflow, 'reserve', lambda amounts: None)
    other = AsyncMock(side_effect=AssertionError('no other cloud'))
    monkeypatch.setattr(chat_gateway, 'proxy_to_modelscope', other)
    return other


@pytest.mark.parametrize('status', [429, 500, 502, 503, 504])
def test_transient_cloud_failure_uses_one_local_attempt(monkeypatch, route, status):
    cloud = AsyncMock(side_effect=HTTPException(status, 'do not forward upstream error'))
    local = AsyncMock(return_value=JSONResponse({'ok': True}))
    monkeypatch.setattr(chat_gateway, 'proxy_openai', cloud)
    monkeypatch.setattr(chat_gateway, 'proxy_to_ollama', local)
    payload = {'model': siliconflow.CHAT_MODEL, 'stream': True, 'tools': [{'name': 'move'}],
               'messages': [{'role': 'system', 'content': 'private context'},
                            {'role': 'user', 'content': [{'type': 'text', 'text': '講個太空故事'},
                                {'type': 'image_url', 'image_url': {'url': 'private image'}}]}]}
    response = asyncio.run(chat_gateway.route_chat(payload, OfflineFaq()))
    assert response.headers['X-Zhiwei-Chat-Route'] == 'ollama-fallback'
    cloud.assert_awaited_once()
    local.assert_awaited_once()
    forwarded = local.call_args.args[2]
    assert forwarded['model'] == 'qwen3:1.7b'
    assert forwarded['stream'] is True
    assert 'tools' not in forwarded
    assert 'private' not in str(forwarded)
    assert 'synthetic-key' not in str(forwarded)
    route.assert_not_called()


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422])
def test_invalid_request_or_authentication_error_not_hidden(monkeypatch, route, status):
    monkeypatch.setattr(chat_gateway, 'proxy_openai', AsyncMock(side_effect=HTTPException(status)))
    local = AsyncMock()
    monkeypatch.setattr(chat_gateway, 'proxy_to_ollama', local)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(chat_gateway.route_chat(
            {'messages': [{'role': 'user', 'content': '講個太空故事'}]}, OfflineFaq()))
    assert failure.value.status_code == status
    local.assert_not_called()


def test_both_routes_failed_returns_fixed_safe_error(monkeypatch, route):
    monkeypatch.setattr(chat_gateway, 'proxy_openai', AsyncMock(side_effect=httpx.ConnectError('secret')))
    local = AsyncMock(side_effect=httpx.ConnectError('private upstream response'))
    monkeypatch.setattr(chat_gateway, 'proxy_to_ollama', local)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(chat_gateway.route_chat(
            {'messages': [{'role': 'user', 'content': '講個太空故事'}]}, OfflineFaq()))
    assert failure.value.status_code == 503
    assert '本機備援亦未能回覆' in failure.value.detail
    assert 'secret' not in failure.value.detail
    local.assert_awaited_once()


def test_stream_failure_after_response_is_not_replayed(monkeypatch, route):
    async def broken_stream():
        yield b'data: first-part\n\n'
        raise httpx.ReadError('connection lost after output')

    monkeypatch.setattr(chat_gateway, 'proxy_openai', AsyncMock(
        return_value=StreamingResponse(broken_stream())))
    local = AsyncMock()
    monkeypatch.setattr(chat_gateway, 'proxy_to_ollama', local)

    async def run():
        response = await chat_gateway.route_chat(
            {'stream': True, 'messages': [{'role': 'user', 'content': '講個太空故事'}]}, OfflineFaq())
        chunks = []
        with pytest.raises(httpx.ReadError):
            async for chunk in response.body_iterator:
                chunks.append(chunk)
        assert len(chunks) == 1

    asyncio.run(run())
    local.assert_not_called()


def test_cancelled_cloud_request_does_not_start_local_work(monkeypatch, route):
    monkeypatch.setattr(chat_gateway, 'proxy_openai', AsyncMock(side_effect=asyncio.CancelledError()))
    local = AsyncMock()
    monkeypatch.setattr(chat_gateway, 'proxy_to_ollama', local)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(chat_gateway.route_chat(
            {'messages': [{'role': 'user', 'content': '講個太空故事'}]}, OfflineFaq()))
    local.assert_not_called()


def test_health_exposes_loaded_fallback_contract_without_secrets(monkeypatch):
    import importlib

    hub = importlib.import_module('edge_hub.app')
    monkeypatch.setattr(hub, 'siliconflow_enabled', lambda: True)
    failover = hub.health()['chat_failover']
    assert failover == {'version': 1, 'enabled': True, 'target': 'ollama',
                        'model': 'qwen3:1.7b', 'cloud_retries': 0,
                        'other_cloud_fallback': False, 'after_stream_started': False}
