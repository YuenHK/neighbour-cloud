import asyncio
import json
from types import SimpleNamespace

import pytest

from edge_hub.observability import HttpMetrics, MetricsMiddleware


@pytest.mark.parametrize('failure', [None, 'send', 'cancel', 'handler'])
def test_body_counts_only_successful_send_returns(failure):
    metrics = HttpMetrics()
    chunks = [b'private first', b'private second', b'']

    async def handler(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        for index, body in enumerate(chunks):
            if index == 1 and failure == 'handler':
                raise RuntimeError('private failure')
            await send({'type': 'http.response.body', 'body': body, 'more_body': index < 2})

    messages = 0

    async def send(message):
        nonlocal messages
        if message['type'] == 'http.response.body':
            messages += 1
            if messages == 2:
                if failure == 'send':
                    raise OSError('private transport')
                if failure == 'cancel':
                    raise asyncio.CancelledError('private cancellation')

    wrapped = MetricsMiddleware(handler, metrics)
    scope = {'type': 'http', 'method': 'GET', 'path': '/private-id',
             'route': SimpleNamespace(path='/items/{id}')}
    if failure:
        error = {'send': OSError, 'cancel': asyncio.CancelledError, 'handler': RuntimeError}[failure]
        with pytest.raises(error):
            asyncio.run(wrapped(scope, None, send))
    else:
        asyncio.run(wrapped(scope, None, send))
    report = metrics.snapshot()
    expected_bytes = len(chunks[0]) if failure else sum(map(len, chunks))
    expected_messages = 1 if failure else 3
    for counters in (report, report['routes'][0]):
        assert counters['response_body_bytes_sent'] == expected_bytes
        assert counters['response_body_messages_sent'] == expected_messages
    assert report['aborted_requests'] == int(failure is not None)
    assert report['in_flight'] == 0
    assert 'not delivery ACK' in report['response_body_scope']
    assert 'private' not in json.dumps(report)


def test_overflow_and_snapshot_do_not_lose_counts_or_persist_them():
    metrics = HttpMetrics(max_routes=1, window=1)
    for route in ['/first', '/second', '/third']:
        metrics.begin()
        metrics.finish('GET', route, 200, .1, body_bytes=7, body_messages=2)
    report = metrics.snapshot()
    assert len(report['routes']) == 2
    overflow = next(row for row in report['routes'] if row['route'] == 'overflow')
    assert overflow['response_body_bytes_sent'] == 14
    assert overflow['response_body_messages_sent'] == 4
    report['routes'][0]['response_body_bytes_sent'] = -1
    assert metrics.snapshot()['response_body_bytes_sent'] == 21
    assert all(row['response_body_bytes_sent'] >= 0 for row in metrics.snapshot()['routes'])
    assert HttpMetrics().snapshot()['response_body_bytes_sent'] == 0
