import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from edge_hub import siliconflow
from edge_hub.chat_gateway import route_chat
from edge_hub.faq import OfflineFaq


def test_route_pins_free_model_and_removes_tools_and_images(monkeypatch):
    result = object()
    proxy = AsyncMock(return_value=result)
    monkeypatch.setattr('edge_hub.chat_gateway.siliconflow_enabled', lambda: True)
    monkeypatch.setattr('edge_hub.chat_gateway.siliconflow_key', lambda: 'test-key')
    monkeypatch.setattr('edge_hub.chat_gateway.proxy_openai', proxy)
    monkeypatch.setattr(siliconflow, 'reserve', lambda amounts: None)
    payload = {'model': 'paid/model', 'stream': True, 'tools': [{'name': 'drive'}],
               'messages': [{'role': 'system', 'content': 'untrusted prompt'},
                            {'role': 'user', 'content': [
                                {'type': 'text', 'text': '請講一個太空故事'},
                                {'type': 'image_url', 'image_url': {'url': 'private-image'}}]}]}
    assert asyncio.run(route_chat(payload, OfflineFaq())) is result
    forwarded = proxy.call_args.args[2]
    assert forwarded['model'] == 'XingChenAGI/Xing4.0-29B'
    assert 'private-image' not in str(forwarded)
    assert 'untrusted prompt' not in str(forwarded)
    assert 'tools' not in forwarded
    assert forwarded['enable_thinking'] is False


def test_network_failure_falls_back_only_to_local_ollama(monkeypatch):
    local = AsyncMock(return_value=JSONResponse({'ok': True}))
    monkeypatch.setattr('edge_hub.chat_gateway.siliconflow_enabled', lambda: True)
    monkeypatch.setattr('edge_hub.chat_gateway.siliconflow_key', lambda: 'test-key')
    monkeypatch.setattr(siliconflow, 'reserve', lambda amounts: None)
    monkeypatch.setattr('edge_hub.chat_gateway.proxy_to_ollama', local)
    monkeypatch.setattr('edge_hub.chat_gateway.proxy_openai',
                        AsyncMock(side_effect=httpx.ConnectError('offline')))
    other_cloud = AsyncMock(side_effect=AssertionError('another cloud must not be used'))
    monkeypatch.setattr('edge_hub.chat_gateway.proxy_to_modelscope', other_cloud)
    result = asyncio.run(route_chat({'model': siliconflow.CHAT_MODEL,
                                    'messages': [{'role': 'user', 'content': '講個太空故事'}]},
                                   OfflineFaq()))
    assert result.headers['X-Zhiwei-Chat-Route'] == 'ollama-fallback'
    assert result.headers['X-Zhiwei-Cloud-Result'] == 'network-error'
    local.assert_awaited_once()
    assert local.call_args.args[2]['model'] == 'qwen3:1.7b'
    other_cloud.assert_not_called()


def test_limit_rejection_happens_before_network(monkeypatch):
    proxy = AsyncMock()
    monkeypatch.setattr('edge_hub.chat_gateway.siliconflow_enabled', lambda: True)
    monkeypatch.setattr('edge_hub.chat_gateway.siliconflow_key', lambda: 'test-key')
    monkeypatch.setattr('edge_hub.chat_gateway.proxy_openai', proxy)
    local = AsyncMock(return_value=JSONResponse({'ok': True}))
    monkeypatch.setattr('edge_hub.chat_gateway.proxy_to_ollama', local)

    def reject(_):
        raise HTTPException(429, 'local limit')

    monkeypatch.setattr(siliconflow, 'reserve', reject)
    result = asyncio.run(route_chat({'messages': [{'role': 'user', 'content': '講個太空故事'}]},
                                   OfflineFaq()))
    assert result.headers['X-Zhiwei-Cloud-Result'] == 'http-429'
    proxy.assert_not_called()
    local.assert_awaited_once()


def test_audio_over_limit_is_not_sent():
    with pytest.raises(HTTPException) as error:
        asyncio.run(siliconflow.transcribe(b'audio', 46))
    assert error.value.status_code == 400


def test_transcription_reuses_supplied_connection_without_recreating_it(monkeypatch):
    connection = AsyncMock()
    connection.post.return_value = httpx.Response(200, json={'text': '你好'})
    monkeypatch.setattr(siliconflow, 'siliconflow_key', lambda: 'test-key')
    monkeypatch.setattr(siliconflow, 'reserve', lambda amounts: None)
    factory = AsyncMock(side_effect=AssertionError('must reuse connection'))
    monkeypatch.setattr(siliconflow.httpx, 'AsyncClient', factory)
    assert asyncio.run(siliconflow.transcribe(b'wav', 1, client=connection)) == '你好'
    factory.assert_not_called()
    connection.aclose.assert_not_called()


def test_privacy_faq_discloses_cloud_audio(monkeypatch):
    monkeypatch.setattr('edge_hub.faq.siliconflow_enabled', lambda: True)
    answer = OfflineFaq().query('聲音私隱').answer
    assert '硅基流動' in answer
    assert '即時本地辨識' not in answer


def test_cross_origin_chat_request_is_rejected():
    from fastapi.testclient import TestClient

    from edge_hub.app import app

    result = TestClient(app).post('/v1/chat/completions',
                                  headers={'Origin': 'https://untrusted.example'}, json={})
    assert result.status_code == 403


def test_transcription_sends_only_free_model_and_returns_text(monkeypatch):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            assert url == 'https://api.siliconflow.cn/v1/audio/transcriptions'
            assert kwargs['data'] == {'model': 'FunAudioLLM/SenseVoiceSmall'}
            assert kwargs['files']['file'] == ('speech.wav', b'wav', 'audio/wav')
            return httpx.Response(200, json={'text': '你好，我係 Anson。'})

    monkeypatch.setattr(siliconflow, 'siliconflow_key', lambda: 'test-key')
    monkeypatch.setattr(siliconflow, 'reserve', lambda amounts: None)
    monkeypatch.setattr(siliconflow.httpx, 'AsyncClient', lambda **kwargs: Client())
    assert asyncio.run(siliconflow.transcribe(b'wav', 3)) == '你好，我係 Anson。'
