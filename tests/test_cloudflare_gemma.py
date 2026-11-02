import asyncio
import json

import httpx
import pytest

from edge_hub import cloudflare_gemma as cf
from edge_hub.cloud_allowance import CloudAllowance
from edge_hub.resident_cloud import CloudUnavailable


class Events(httpx.AsyncByteStream):
    def __init__(self, fail=False):
        self.fail, self.closed = fail, False

    async def __aiter__(self):
        yield ('data: '+json.dumps({'choices': [{'delta': {'content': '記得你講香蕉蛋糕。'}}]})+'\n\n').encode()
        if self.fail:
            raise httpx.ReadError('private upstream detail')
        yield b'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}\n\n'
        yield b'data: [DONE]\n\n'

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(cf, 'settings_root', lambda: tmp_path)
    monkeypatch.setattr(cf, '_crypt', lambda *a, **k: b'synthetic-key')
    monkeypatch.setattr(cf, '_busy', False)
    monkeypatch.setattr(cf, '_until', 0)
    monkeypatch.setattr(cf, '_last', {'last_route': 'not_used', 'last_failure': None, 'last_elapsed_ms': None})
    (tmp_path/'cloudflare-gemma-key.dpapi').write_bytes(b'encrypted-synthetic')
    (tmp_path/'cloudflare-gemma-free.json').write_text(json.dumps(
        {'enabled': True, 'plan': 'Free', 'ui_verified': True, 'account_id': 'a'*32}))


def history(stream=True):
    return {'stream': stream, 'model': 'paid-user-override', 'messages': [
        {'role': 'user', 'content': '想焗香蕉蛋糕。'}, {'role': 'assistant', 'content': '今日可以慢慢嚟。'},
        {'role': 'user', 'content': '你記得係咩嗎？'}]}


def test_fixed_free_model_preserves_complete_context_and_stream_lifecycle():
    calls, stream = [], Events()
    def respond(request):
        calls.append(request)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await cf.complete(history(), prompt='AIRI persona', context='verified data', client=client)
            assert cf._busy
            body = b''.join([p async for p in response.body_iterator]).decode()
            assert '香蕉蛋糕' in body and body.count('[DONE]') == 1
            assert response.headers['x-resident-route'] == 'gemma-cloudflare-free'
    asyncio.run(run())
    assert len(calls) == 1 and stream.closed and not cf._busy
    body = json.loads(calls[0].content)
    assert body['model'] == cf.MODEL and body['messages'][1:] == history()['messages']
    assert body['messages'][0]['content'].startswith('AIRI persona')
    assert body['max_tokens'] == 384 and body['chat_template_kwargs']['enable_thinking'] is False
    assert 'synthetic-key' not in str(calls[0].url) and 'paid-user-override' not in str(body)


def test_partial_failure_never_commits_done_or_calls_another_provider():
    stream = Events(fail=True)
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await cf.complete(history(), prompt='persona', client=client)
            body = b''.join([p async for p in response.body_iterator])
            assert b'[DONE]' not in body and b'resident_stream_incomplete' in body
            assert b'private' not in body
    asyncio.run(run())
    assert len(calls) == 1 and stream.closed and not cf._busy


def test_platform_daily_quota_persists_stop_and_never_retries_after_restart(tmp_path, monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(429, json={'errors': [{'code': 3036, 'message': 'upgrade to paid'}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(CloudUnavailable):
                await cf.complete(history(), prompt='persona', client=client)
            monkeypatch.setattr(cf, '_until', 0)
            with pytest.raises(CloudUnavailable):
                await cf.complete(history(), prompt='persona', client=client)
    asyncio.run(run())
    assert len(calls) == 1 and (tmp_path/'cloudflare-gemma-quota-stop.json').is_file()


def test_paid_or_corrupt_config_fails_before_any_network(tmp_path):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('no dispatch'))) as client:
            for contents in ('{"enabled":true,"plan":"Paid"}', 'corrupt'):
                (tmp_path/'cloudflare-gemma-free.json').write_text(contents)
                assert cf.selected() and cf.configuration() is None
                with pytest.raises(CloudUnavailable):
                    await cf.complete(history(), prompt='persona', client=client)
    asyncio.run(run())


def test_local_neuron_reservation_exhaustion_stops_before_dispatch(tmp_path):
    CloudAllowance(tmp_path/'cloud-usage.sqlite3').reserve({'cloudflare_gemma_neuron_reservations': 8000})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('no dispatch'))) as client:
            with pytest.raises(CloudUnavailable):
                await cf.complete(history(), prompt='persona', client=client)
    asyncio.run(run())


def test_non_streaming_contract_returns_normal_chat_completion():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,
                headers={'content-type': 'text/event-stream'}, stream=Events()))) as client:
            response = await cf.complete(history(False), prompt='persona', client=client)
            body = json.loads(response.body)
            assert body['choices'][0]['message']['content'] == '記得你講香蕉蛋糕。'
            assert not cf._busy
    asyncio.run(run())


def test_length_diagnostics_never_include_prompt_or_output_text():
    content='synthetic private text without punctuation'
    raw=('data: '+json.dumps({'choices':[{'delta':{'content':content},'finish_reason':'length'}]})+'\n\n').encode()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,
                headers={'content-type':'text/event-stream'},content=raw))) as client:
            with pytest.raises(CloudUnavailable):
                await cf.complete(history(),prompt='private prompt',client=client)
    asyncio.run(run())
    detail=cf.state()['last_failure_detail']
    assert detail['reason']=='incomplete_answer' and detail['finish_reason']=='length'
    assert detail['content_chars']==len(content)
    assert 'private' not in json.dumps(cf.state())


def test_semantic_failure_does_not_block_a_different_manual_message():
    calls=[]
    def respond(request):
        calls.append(request)
        if len(calls)==1:
            return httpx.Response(200,headers={'content-type':'text/event-stream'},
                content=b'data: {"choices":[{"delta":{"content":"unfinished"},"finish_reason":"length"}]}\n\n')
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Events())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(CloudUnavailable):
                await cf.complete(history(),prompt='persona',client=client)
            assert not cf.state()['cooldown']
            assert cf.state()['last_failure_detail']['retry_after_seconds']==0
            response=await cf.complete(history(False),prompt='another question',client=client)
            assert response.status_code==200
    asyncio.run(run())
    assert len(calls)==2  # Deliberate second turn, never an automatic upstream retry.


def test_verified_information_uses_bounded_headroom_and_reserves_before_dispatch(tmp_path):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Events())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response=await cf.complete(history(False),prompt='本輪是一般資訊查詢',client=client)
            assert response.status_code==200
    asyncio.run(run())
    assert json.loads(calls[0].content)['max_tokens']==768
    assert json.loads(calls[0].content)['chat_template_kwargs']['enable_thinking'] is False


def test_information_headroom_cannot_bypass_free_local_reservation_limit(tmp_path):
    CloudAllowance(tmp_path/'cloud-usage.sqlite3').reserve({'cloudflare_gemma_neuron_reservations':7980})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:pytest.fail('quota stopped dispatch'))) as client:
            with pytest.raises(CloudUnavailable):
                await cf.complete(history(False),prompt='本輪是一般資訊查詢',client=client)
    asyncio.run(run())
