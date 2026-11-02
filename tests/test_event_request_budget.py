import asyncio
import importlib
import json

import pytest
from fastapi.testclient import TestClient

from edge_hub.event_request import EventBodyLimitMiddleware
from edge_hub.events import EventStore


def invoke(messages, *, headers=(), max_bytes=12, timeout=.1):
    called, sent = [], []
    pending = iter(messages)
    async def receive():
        return next(pending)
    async def send(message):
        sent.append(message)
    async def app(scope, receive, send):
        called.append(await receive())
        called.append(await receive())
    asyncio.run(EventBodyLimitMiddleware(app, max_bytes, timeout)(
        {'type': 'http', 'method': 'POST', 'path': '/api/v1/events', 'headers': headers}, receive, send))
    return called, sent


def test_oversized_declared_body_rejected_without_reading_or_calling_app():
    called, sent = invoke([], headers=[(b'content-length', b'999999999999999')])
    assert not called and sent[0]['status'] == 413
    assert (b'cache-control', b'no-store') in sent[0]['headers']


@pytest.mark.parametrize('headers', [[], [(b'content-length', b'1')]])
def test_actual_chunks_are_bounded_even_without_or_with_lying_header(headers):
    called, sent = invoke([{'type': 'http.request', 'body': b'private!', 'more_body': True},
                           {'type': 'http.request', 'body': b'private!'}], headers=headers)
    assert not called and sent[0]['status'] == 413
    assert b'private' not in sent[-1]['body']


def test_exact_limit_replays_once_then_forwards_real_disconnect():
    called, sent = invoke([{'type': 'http.request', 'body': b'123456', 'more_body': True},
                           {'type': 'http.request', 'body': b'789012'},
                           {'type': 'http.disconnect'}])
    assert called == [{'type': 'http.request', 'body': b'123456789012', 'more_body': False},
                      {'type': 'http.disconnect'}]
    assert not sent


@pytest.mark.parametrize('headers', [[(b'content-length', b'-1')], [(b'content-length', b'invalid')],
                                    [(b'content-length', b'1'), (b'content-length', b'1')]])
def test_invalid_content_length_is_not_echoed_or_passed_to_app(headers):
    called, sent = invoke([], headers=headers)
    assert not called and sent[0]['status'] == 400
    assert b'invalid event content length' in sent[-1]['body']


def test_disconnected_partial_request_never_reaches_json_parser():
    called, sent = invoke([{'type': 'http.request', 'body': b'{', 'more_body': True},
                           {'type': 'http.disconnect'}])
    assert not called and not sent


def test_slow_body_has_total_timeout_without_downstream_call():
    sent = []
    async def receive():
        await asyncio.sleep(1)
    async def send(message):
        sent.append(message)
    async def app(*args):
        raise AssertionError('timed out body must not reach app')
    asyncio.run(EventBodyLimitMiddleware(app, timeout_seconds=.01)(
        {'type': 'http', 'method': 'POST', 'path': '/api/v1/events'}, receive, send))
    assert sent[0]['status'] == 408


@pytest.mark.parametrize('scope', [{'type': 'websocket'},
                                  {'type': 'http', 'method': 'POST', 'path': '/v1/audio/speech'},
                                  {'type': 'http', 'method': 'GET', 'path': '/api/v1/events'}])
def test_unrelated_routes_pass_through(scope):
    called = []
    async def app(actual, receive, send):
        called.append(actual)
    asyncio.run(EventBodyLimitMiddleware(app)(scope, None, None))
    assert called == [scope]


def test_actual_event_api_rejects_large_body_without_store_change_and_keeps_cors(monkeypatch):
    hub = importlib.import_module('edge_hub.app')
    store = EventStore()
    monkeypatch.setattr(hub, 'store', store)
    monkeypatch.setattr(hub, 'EVENT_INGEST_KEY', 'test-collector')
    payload = {'id': 'small', 'type': 'robot_fault', 'zone': 'test', 'at_ms': 0, 'severity': 'notice'}
    headers = {'X-Event-Ingest-Key': 'test-collector', 'Content-Type': 'application/json',
               'Origin': 'http://127.0.0.1:4173'}
    try:
        client = TestClient(hub.app)
        response = client.post('/api/v1/events', content=json.dumps(payload) + ' ' * 65536,
                               headers=headers)
        assert response.status_code == 413 and store.latest_cursor() == 0
        assert response.headers['access-control-allow-origin'] == 'http://127.0.0.1:4173'
        assert client.post('/api/v1/events', json=payload, headers=headers).status_code == 201
    finally:
        store.close()


def test_receive_timeout_does_not_turn_slow_rejection_send_into_second_response():
    sent = []
    async def receive():
        return {'type': 'http.request', 'body': b'too large'}
    async def send(message):
        await asyncio.sleep(.02)
        sent.append(message)
    async def app(*args):
        raise AssertionError('oversized body must not reach app')
    asyncio.run(EventBodyLimitMiddleware(app, max_bytes=1, timeout_seconds=.01)(
        {'type': 'http', 'method': 'POST', 'path': '/api/v1/events'}, receive, send))
    assert [message['status'] for message in sent if message['type'] == 'http.response.start'] == [413]


def test_immediate_empty_frames_still_yield_to_receive_timeout():
    sent = []
    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': True}
    async def send(message):
        sent.append(message)
    async def app(*args):
        raise AssertionError('endless empty frames must not reach app')
    asyncio.run(EventBodyLimitMiddleware(app, timeout_seconds=.01)(
        {'type': 'http', 'method': 'POST', 'path': '/api/v1/events'}, receive, send))
    assert sent[0]['status'] == 408


def test_external_cancellation_propagates_without_fake_timeout_response():
    sent = []
    async def receive():
        raise asyncio.CancelledError()
    async def send(message):
        sent.append(message)
    async def app(*args):
        raise AssertionError('cancelled body must not reach app')
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(EventBodyLimitMiddleware(app)(
            {'type': 'http', 'method': 'POST', 'path': '/api/v1/events'}, receive, send))
    assert not sent
