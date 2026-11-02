import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from edge_hub import resident_cloud, resident_inference
from edge_hub.cloud_allowance import AllowanceExceeded
from edge_hub.faq import OfflineFaq


class SentenceStream(httpx.AsyncByteStream):
    def __init__(self, events, delay=0):
        self.events, self.delay, self.closed = events, delay, False

    async def __aiter__(self):
        for index, event in enumerate(self.events):
            if index and self.delay:
                await asyncio.sleep(self.delay)
            if isinstance(event, Exception):
                raise event
            yield ('data: '+json.dumps(event, ensure_ascii=False)+'\n\n').encode()

    async def aclose(self):
        self.closed = True


def test_real_sentence_stream_yields_before_completion_and_closes_gate():
    stream = SentenceStream([success('今日真係忙咗成日。', finish=None), success('可以慢慢歇吓。')], delay=.03)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,
                headers={'content-type': 'text/event-stream'}, stream=stream))) as client:
            response = await resident_cloud.complete(payload(stream=True, _sentence_stream=True), prompt='system', client=client, model=resident_cloud.GEMMA_MODEL)
            assert not stream.closed
            first = await anext(response.body_iterator)
            assert '今日' in first.decode() and '[DONE]' not in first.decode()
            rest = b''.join([part async for part in response.body_iterator]).decode()
            assert '慢慢歇' in rest and rest.count('[DONE]') == 1
            assert stream.closed and not resident_cloud._inflight
            assert response.headers['X-Resident-First-Sentence-Ms'].isdigit()
    asyncio.run(scenario())


def test_late_failure_never_mixes_fast_model_or_commits_done():
    calls = []
    stream = SentenceStream([success('先慢慢講。', finish=None), httpx.ReadError('synthetic')])
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await resident_cloud.complete(payload(stream=True, _sentence_stream=True), prompt='system', client=client, model=resident_cloud.GEMMA_MODEL)
            body = b''.join([part async for part in response.body_iterator]).decode()
            assert '先慢慢講' in body and 'resident_stream_incomplete' in body and '[DONE]' not in body
            assert stream.closed and not resident_cloud._inflight
    asyncio.run(scenario())
    assert len(calls) == 1


def test_stream_failure_before_output_uses_fast_with_identical_true_context():
    bodies = []
    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(503) if len(bodies) == 1 else httpx.Response(200, json=success())
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await resident_cloud.complete(payload(stream=True, _sentence_stream=True), prompt='system', client=client, model=resident_cloud.GEMMA_MODEL)
            body = b''.join([part async for part in response.body_iterator]).decode()
            assert '[DONE]' in body and response.headers['X-Resident-Model'] == resident_cloud.FAST_MODEL
    asyncio.run(scenario())
    assert len(bodies) == 2 and '今日飲茶幾舒服' in bodies[0]['contents'][0]['parts'][0]['text']
    assert bodies[1]['contents'][0]['parts'][0]['text'] == '今日飲茶幾舒服'


def test_abandoned_response_releases_upstream_without_reading_rest():
    stream = SentenceStream([success('先慢慢講。', finish=None), success('可以休息。')], delay=5)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,
                headers={'content-type': 'text/event-stream'}, stream=stream))) as client:
            response = await resident_cloud.complete(payload(stream=True, _sentence_stream=True), prompt='system', client=client, model=resident_cloud.GEMMA_MODEL)
            await response.background()
            assert stream.closed and not resident_cloud._inflight and not client.is_closed
    asyncio.run(scenario())


def test_stream_absolute_deadline_stops_slow_tail_without_fallback(monkeypatch):
    monkeypatch.setitem(resident_cloud.DEADLINES, resident_cloud.GEMMA_MODEL, .03)
    stream = SentenceStream([success('先慢慢講。', finish=None), success('第二句。')], delay=.1)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,
                headers={'content-type': 'text/event-stream'}, stream=stream))) as client:
            response = await resident_cloud.complete(payload(stream=True, _sentence_stream=True), prompt='system', client=client, model=resident_cloud.GEMMA_MODEL)
            body = b''.join([part async for part in response.body_iterator]).decode()
            assert '[DONE]' not in body and 'resident_stream_incomplete' in body
            assert stream.closed and not resident_cloud._inflight
    asyncio.run(scenario())


@pytest.fixture(autouse=True)
def isolated_cloud(monkeypatch):
    from edge_hub import cloudflare_gemma
    monkeypatch.setattr(cloudflare_gemma, 'selected', lambda: False)
    monkeypatch.setattr(resident_cloud, '_cooldowns', {})
    monkeypatch.setattr(resident_cloud, '_inflight', set())
    monkeypatch.setattr(resident_cloud, '_last_route', 'not_used')
    monkeypatch.setattr(resident_cloud, '_last_failure', None)
    monkeypatch.setattr(resident_cloud, '_last_model', None)
    monkeypatch.setattr(resident_cloud, '_last_elapsed_ms', None)
    monkeypatch.setattr(resident_cloud, 'key', lambda: 'synthetic-key')
    monkeypatch.setattr(resident_cloud, 'reserve', lambda count: None)


def payload(**extra):
    return {'messages': [{'role': 'system', 'content': 'untrusted-system'},
                         {'role': 'user', 'content': '今日飲茶幾舒服'}], **extra}


def success(text='慢慢嘆杯茶，幾舒服。', finish='STOP'):
    return {'candidates': [{'finishReason': finish, 'content': {'parts': [{'text': text}]}}]}


def test_only_fixed_free_model_and_bounded_real_history_are_sent():
    captured = []
    def respond(request):
        captured.append(request)
        return httpx.Response(200, json=success())
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await resident_cloud.complete(payload(stream=True, model='paid-model', tools=[{'name': 'move_robot'}]), prompt='trusted-system', client=client)
            body = b''.join([chunk async for chunk in response.body_iterator]).decode()
            assert body.count('[DONE]') == 1 and '慢慢嘆' in body
            assert not client.is_closed
            assert response.headers['X-Resident-Model'] == resident_cloud.MODEL
    asyncio.run(scenario())
    body = json.loads(captured[0].content)
    assert str(captured[0].url) == resident_cloud.URL
    assert 'synthetic-key' not in str(captured[0].url)
    assert 'paid-model' not in str(body) and 'move_robot' not in str(body)
    assert 'untrusted-system' not in str(body)
    assert body['contents'] == [{'role': 'user', 'parts': [{'text': '今日飲茶幾舒服'}]}]


@pytest.mark.parametrize('status', [401, 403, 429, 500, 503])
def test_failure_is_not_retried_and_cooldown_prevents_another_request(status):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={'error': {'message': 'sensitive upstream text'}})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            for _ in range(2):
                with pytest.raises(resident_cloud.CloudUnavailable) as error:
                    await resident_cloud.complete(payload(), prompt='system', client=client)
                assert 'sensitive' not in str(error.value)
            assert resident_cloud.state()['cooldown']
            assert resident_cloud.state()['provider_remaining'] is None
    asyncio.run(scenario())
    assert len(calls) == 1


def test_local_allowance_exhaustion_never_dispatches_cloud(monkeypatch):
    def reserve(count):
        raise AllowanceExceeded('local_guard')
    monkeypatch.setattr(resident_cloud, 'reserve', reserve)
    def respond(request):
        pytest.fail('exhausted allowance must not dispatch')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(resident_cloud.CloudUnavailable):
                await resident_cloud.complete(payload(), prompt='system', client=client)
    asyncio.run(scenario())


@pytest.mark.parametrize('data', [success(''), success('unfinished', 'MAX_TOKENS'), {'candidates': []}])
def test_incomplete_or_empty_cloud_answer_is_not_delivered(data):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))) as client:
            with pytest.raises(resident_cloud.CloudUnavailable):
                await resident_cloud.complete(payload(stream=True), prompt='system', client=client)
    asyncio.run(scenario())


def test_sourced_context_keeps_links_and_questions_intact():
    answer = '來源：https://example.org/official。你可查看來源。'
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=success(answer)))) as client:
            response = await resident_cloud.complete(payload(), prompt='system', context='核對來源：https://example.org/official', client=client)
            assert json.loads(response.body)['choices'][0]['message']['content'] == answer
    asyncio.run(scenario())


def test_cloud_failure_does_not_switch_models_and_explicit_memory_stays_local(monkeypatch):
    monkeypatch.setattr(resident_inference, 'configuration', lambda: {'mode': 'gemini-free'})
    cloud = AsyncMock(side_effect=resident_cloud.CloudUnavailable('unavailable'))
    local = AsyncMock(return_value=JSONResponse({'ok': True}))
    other = AsyncMock(side_effect=AssertionError('no other cloud'))
    monkeypatch.setattr(resident_cloud, 'complete', cloud)
    monkeypatch.setattr(resident_inference, 'native_local', local)
    monkeypatch.setattr(resident_inference, 'route_chat', other)
    with pytest.raises(HTTPException) as unavailable:
        asyncio.run(resident_inference.resident_chat(payload(), OfflineFaq()))
    assert unavailable.value.status_code == 503
    local.assert_not_called()
    cloud.assert_awaited_once()
    response = asyncio.run(resident_inference.resident_chat(payload(_local_only=True, _service_context='explicit private memory'), OfflineFaq()))
    assert response.headers['X-Resident-Route'] == 'local-only'
    cloud.assert_awaited_once()
    assert local.await_count == 1
    other.assert_not_called()
    local.side_effect = httpx.ConnectError('private text')
    with pytest.raises(HTTPException) as error:
        asyncio.run(resident_inference.resident_chat(payload(), OfflineFaq()))
    assert error.value.status_code == 503 and 'private' not in error.value.detail
    other.assert_not_called()


def test_quota_reports_local_reservations_without_inventing_provider_balance(monkeypatch, tmp_path):
    from edge_hub import api_quota
    from edge_hub.cloud_allowance import CloudAllowance
    monkeypatch.setattr(api_quota, 'settings_root', lambda: tmp_path)
    CloudAllowance(tmp_path/'cloud-usage.sqlite3').reserve({'gemini_chat_requests': 2})
    snapshot = api_quota.resident_chat_usage()
    assert snapshot['used'] == 2 and snapshot['scope'] == 'local_guard_only'
    assert snapshot['provider_remaining'] is None


def test_gemma_success_uses_verified_minimal_content_format_without_mutating_history():
    from edge_hub.resident_models import GEMMA_MODEL
    captured = []
    original = payload(stream=True)
    before = json.loads(json.dumps(original))
    def respond(request):
        captured.append(request)
        return httpx.Response(200, json=success('慢慢飲杯茶，今日可以抖吓。'))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await resident_cloud.complete(original, prompt='trusted instruction', model=GEMMA_MODEL, client=client)
            body = b''.join([chunk async for chunk in response.body_iterator]).decode()
            assert body.count('[DONE]') == 1
            assert response.headers['X-Resident-Route'] == 'gemma-free'
            assert response.headers['X-Resident-Model'] == GEMMA_MODEL
    asyncio.run(scenario())
    assert original == before and len(captured) == 1
    body = json.loads(captured[0].content)
    assert 'systemInstruction' not in body and 'tools' not in body
    assert body['contents'][0]['parts'][0]['text'].startswith('trusted instruction')
    assert body['generationConfig']['thinkingConfig']['thinkingLevel'] == 'minimal'
    assert body['generationConfig']['maxOutputTokens'] == 384


@pytest.mark.parametrize('status', [429, 500, 503])
def test_gemma_failure_uses_fast_once_and_cooldown_is_per_model(status):
    from edge_hub.resident_models import FAST_MODEL, GEMMA_MODEL
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={}) if GEMMA_MODEL in request.url.path else httpx.Response(200, json=success())
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            for _ in range(2):
                response = await resident_cloud.complete(payload(), prompt='system', model=GEMMA_MODEL, client=client)
                assert response.headers['X-Resident-Route'] == 'gemini-fast-fallback'
                assert response.headers['X-Resident-Model'] == FAST_MODEL
            assert resident_cloud.state(GEMMA_MODEL)['cooldown']
            assert not resident_cloud.state(FAST_MODEL)['cooldown']
    asyncio.run(scenario())
    assert [GEMMA_MODEL in request.url.path for request in requests] == [True, False, False]


def test_wall_clock_deadline_discards_partial_body_before_fast_fallback(monkeypatch):
    from edge_hub.resident_models import FAST_MODEL, GEMMA_MODEL
    monkeypatch.setattr(resident_cloud, 'DEADLINES', {GEMMA_MODEL: .03, FAST_MODEL: 1})
    calls = []
    class SlowBody(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            yield b'{"candidates":[{"content":{"parts":[{"text":"partial answer'
            await asyncio.sleep(10)
        async def aclose(self):
            self.closed = True
    slow = SlowBody()
    async def respond(request):
        calls.append(request)
        return httpx.Response(200, stream=slow) if GEMMA_MODEL in request.url.path else httpx.Response(200, json=success('完整快速回覆。'))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await resident_cloud.complete(payload(stream=True), prompt='system', model=GEMMA_MODEL, client=client)
            body = b''.join([chunk async for chunk in response.body_iterator]).decode()
            assert '完整快速回覆' in body and 'partial' not in body
            assert body.count('[DONE]') == 1
            assert resident_cloud.state(GEMMA_MODEL)['last_failure'] == 'gemma_timeout'
    asyncio.run(scenario())
    assert len(calls) == 2 and slow.closed and not resident_cloud._inflight


@pytest.mark.parametrize('stream', [False, True])
def test_production_gemma_failure_never_dispatches_fast_or_local(monkeypatch, stream):
    from edge_hub.resident_models import GEMMA_MODEL
    monkeypatch.setattr(resident_inference, 'configuration', lambda: {'mode': 'gemini-free', 'cloud_model': GEMMA_MODEL, 'model': 'local-test'})
    local = AsyncMock(return_value=JSONResponse({'ok': True}))
    other = AsyncMock(side_effect=AssertionError('no other provider'))
    monkeypatch.setattr(resident_inference, 'native_local', local)
    monkeypatch.setattr(resident_inference, 'route_chat', other)
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(500, json={})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(HTTPException) as error:
                await resident_inference.resident_chat(payload(stream=stream), OfflineFaq(), cloud_client=client)
            assert error.value.status_code == 503
    asyncio.run(scenario())
    assert len(calls) == 1
    local.assert_not_called()
    other.assert_not_called()


def test_unapproved_models_are_rejected_before_credentials_or_dispatch(monkeypatch):
    monkeypatch.setattr(resident_cloud, 'key', lambda: pytest.fail('must not load a key'))
    with pytest.raises(resident_cloud.CloudUnavailable):
        asyncio.run(resident_cloud.complete(payload(), prompt='system', model='gemma-4-31b-it'))


def test_failure_details_keep_status_without_provider_text_or_credentials():
    response = httpx.Response(500, json={'error': {'message': 'private provider data'}},
        request=httpx.Request('POST', 'https://example.test?key=secret'))
    error = httpx.HTTPStatusError('secret', request=response.request, response=response)
    resident_cloud.failure_detail(error, response)
    detail = resident_cloud.state()['last_failure_detail']
    assert detail == {'type': 'HTTPStatusError', 'http_status': 500}
    assert 'secret' not in json.dumps(detail) and 'private' not in json.dumps(detail)


def test_gemma_primary_never_receives_named_memory(monkeypatch):
    from edge_hub.resident_models import GEMMA_MODEL
    monkeypatch.setattr(resident_inference, 'configuration', lambda: {'mode': 'gemini-free', 'cloud_model': GEMMA_MODEL})
    cloud = AsyncMock(side_effect=AssertionError('private memory must stay local'))
    local = AsyncMock(return_value=JSONResponse({'ok': True}))
    monkeypatch.setattr(resident_cloud, 'complete', cloud)
    monkeypatch.setattr(resident_inference, 'native_local', local)
    response = asyncio.run(resident_inference.resident_chat(payload(_local_only=True, _service_context='private memory'), OfflineFaq()))
    assert response.headers['X-Resident-Route'] == 'local-only'
    cloud.assert_not_called()
    local.assert_awaited_once()


def test_fallback_keeps_every_turn_of_the_same_short_session():
    from edge_hub.resident_models import FAST_MODEL, GEMMA_MODEL
    history = [{'role': role, 'content': f'{index}: '+('最初分享香蕉蛋糕' if index == 0 else '真實本輪對話')}
               for index, role in enumerate(['user', 'assistant']*20+['user'])]
    original = json.loads(json.dumps(history))
    captured = []
    def respond(request):
        captured.append((str(request.url), json.loads(request.content)))
        return httpx.Response(503 if len(captured) == 1 else 200, json=success())
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await resident_cloud.complete({'messages': history}, prompt='trusted-system', model=GEMMA_MODEL, client=client)
            assert response.headers['X-Resident-Model'] == FAST_MODEL
    asyncio.run(scenario())
    assert len(captured) == 2 and history == original
    gemma = captured[0][1]['contents']
    fast = captured[1][1]['contents']
    assert len(gemma) == len(fast) == 41
    assert gemma[1:] == fast[1:]
    assert gemma[0]['parts'][0]['text'].endswith(history[0]['content'])
    assert fast[0]['parts'][0]['text'] == history[0]['content']
    assert fast[-1]['parts'][0]['text'] == history[-1]['content']
