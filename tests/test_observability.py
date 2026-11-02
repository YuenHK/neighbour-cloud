import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from edge_hub.observability import HttpMetrics, MetricsMiddleware


def test_metrics_are_bounded_and_do_not_retain_identifiers():
    metrics = HttpMetrics(max_routes=2, window=3)
    for index in range(20):
        metrics.begin()
        metrics.finish("GET", f"/route-{index}", 200, index / 1000)
    report = metrics.snapshot()
    assert len(report["routes"]) <= 3  # two known groups plus one overflow group
    assert report["total_requests"] == 20
    assert report["in_flight"] == 0
    assert all(item["window_samples"] <= 3 for item in report["routes"])


def test_latency_and_error_counts():
    metrics = HttpMetrics(window=3)
    for ms in [1, 2, 3, 10]:
        metrics.begin()
        metrics.finish("GET", "/health", 200, ms / 1000)
    metrics.begin()
    metrics.finish("POST", "/events", 500, .5, aborted=True)
    report = metrics.snapshot()
    healthy = next(row for row in report["routes"] if row["route"] == "/health")
    assert healthy["count"] == 4
    assert healthy["p50_ms"] == 3
    assert healthy["p95_ms"] == 10
    assert report["server_errors"] == 1
    assert report["aborted_requests"] == 1


def test_first_nonempty_chunk_is_distinct_from_completion_and_not_audio_acceptance():
    metrics = HttpMetrics()
    async def stream(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'', 'more_body': True})
        await asyncio.sleep(.01)
        await send({'type': 'http.response.body', 'body': b'first', 'more_body': True})
        await asyncio.sleep(.02)
        await send({'type': 'http.response.body', 'body': b'last'})
    async def send(_):
        pass
    asyncio.run(MetricsMiddleware(stream, metrics)({'type':'http', 'method':'POST'}, None, send))
    report = metrics.snapshot()
    row = report['routes'][0]
    assert row['first_body_samples'] == 1
    assert row['first_body_p50_ms'] < row['p50_ms']
    assert 'not browser receipt' in report['first_body_scope']


def test_pre_response_failure_is_counted_and_propagated():
    metrics = HttpMetrics()

    async def broken(scope, receive, send):
        raise ValueError("private failure")

    wrapped = MetricsMiddleware(broken, metrics)
    with pytest.raises(ValueError):
        asyncio.run(wrapped({"type": "http", "method": "POST"}, None, None))
    report = metrics.snapshot()
    assert report["server_errors"] == report["aborted_requests"] == 1
    assert report["in_flight"] == 0
    assert "private" not in json.dumps(report)


def test_websocket_is_forwarded_without_http_metrics():
    metrics = HttpMetrics()
    called = []

    async def websocket(scope, receive, send):
        called.append(scope["type"])

    asyncio.run(MetricsMiddleware(websocket, metrics)({"type": "websocket"}, None, None))
    assert called == ["websocket"]
    assert metrics.snapshot()["total_requests"] == 0


def test_dynamic_route_parameters_are_not_metric_labels():
    from fastapi import FastAPI

    app = FastAPI()
    metrics = HttpMetrics()
    app.add_middleware(MetricsMiddleware, metrics=metrics)

    @app.get("/items/{item_id}")
    def item(item_id: str):
        return {"item": item_id}

    client = TestClient(app)
    client.get("/items/private-id?token=secret")
    report = metrics.snapshot()
    assert report["routes"][0]["route"] == "/items/{item_id}"
    assert "private-id" not in json.dumps(report)
    assert "secret" not in json.dumps(report)


def test_asgi_stream_completion_and_errors_without_private_content():
    metrics = HttpMetrics()

    async def handler(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"private answer", "more_body": True})
        raise RuntimeError("secret failure message")

    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"private question"}

    wrapped = MetricsMiddleware(handler, metrics=metrics)
    try:
        asyncio.run(wrapped({"type": "http", "method": "GET", "path": "/secret-id",
                             "query_string": b"token=secret"}, receive, send))
    except RuntimeError:
        pass
    else:
        raise AssertionError("exception must propagate")
    report = metrics.snapshot()
    assert report["aborted_requests"] == 1
    assert report["in_flight"] == 0
    assert "secret" not in json.dumps(report)
    assert "private" not in json.dumps(report)
    assert any(key == b"x-request-id" for key, _ in sent[0]["headers"])


def test_metrics_endpoint_requires_nondefault_operator_and_hides_raw_paths(monkeypatch):
    from edge_hub import app as hub

    monkeypatch.setattr(hub, "OPERATOR_KEY", "metrics-test-key")
    client = TestClient(hub.app)
    assert client.get("/api/v1/diagnostics/metrics").status_code == 403
    assert client.get("/api/v1/diagnostics/metrics",
                      headers={"X-Event-Ingest-Key": "unit-test-collector-only"}).status_code == 403
    response = client.get("/health?token=do-not-log", headers={"X-Request-ID": "user-secret"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] != "user-secret"
    for index in range(10):
        client.get(f"/missing/private-{index}?token=secret")
    response = client.get("/api/v1/diagnostics/metrics", headers={"X-Operator-Key": "metrics-test-key"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "private-" not in response.text
    assert "do-not-log" not in response.text
    assert "metrics-test-key" not in response.text
    assert any(row["route"] == "unmatched" for row in response.json()["routes"])
    monkeypatch.setattr(hub, "OPERATOR_KEY", "local-operator")
    assert client.get("/api/v1/diagnostics/metrics",
                      headers={"X-Operator-Key": "local-operator"}).status_code == 503


@pytest.mark.parametrize('phase', ['before_start', 'streaming', 'after_final'])
def test_exceptions_are_recorded_even_after_success_status_or_final_body(phase):
    metrics = HttpMetrics()
    async def handler(scope, receive, send):
        if phase != 'before_start':
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'private body',
                        'more_body': phase == 'streaming'})
        raise RuntimeError('private error')
    async def send(message):
        pass
    with pytest.raises(RuntimeError):
        asyncio.run(MetricsMiddleware(handler, metrics)({'type': 'http', 'method': 'GET'},
                                                       None, send))
    report = metrics.snapshot()
    assert report['exception_requests'] == 1
    assert report['cancelled_requests'] == 0
    assert report['server_errors'] == int(phase == 'before_start')
    assert report['aborted_requests'] == int(phase != 'after_final')
    assert report['in_flight'] == 0 and report['total_requests'] == 1
    assert report['routes'][0]['exceptions'] == 1
    assert 'private' not in json.dumps(report)


@pytest.mark.parametrize('started', [False, True])
def test_cancellation_propagates_and_is_distinct_from_exception(started):
    metrics = HttpMetrics()
    async def handler(scope, receive, send):
        if started:
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        raise asyncio.CancelledError('private cancellation')
    async def send(message):
        pass
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(MetricsMiddleware(handler, metrics)({'type': 'http', 'method': 'POST'},
                                                       None, send))
    report = metrics.snapshot()
    assert report['cancelled_requests'] == 1 and report['exception_requests'] == 0
    assert report['routes'][0]['cancelled'] == 1
    assert report['aborted_requests'] == 1 and report['in_flight'] == 0
    assert 'private' not in json.dumps(report)


def test_send_failure_is_counted_without_claiming_delivery():
    metrics = HttpMetrics()
    async def handler(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'private body'})
    async def send(message):
        if message['type'] == 'http.response.body':
            raise OSError('private transport error')
    with pytest.raises(OSError):
        asyncio.run(MetricsMiddleware(handler, metrics)({'type': 'http', 'method': 'GET'},
                                                       None, send))
    report = metrics.snapshot()
    assert report['exception_requests'] == report['aborted_requests'] == 1
    assert report['server_errors'] == 0 and report['in_flight'] == 0
    assert report['routes'][0]['statuses'] == {'200': 1}
    assert 'private' not in json.dumps(report)
