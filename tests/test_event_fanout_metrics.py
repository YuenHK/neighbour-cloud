import asyncio
import importlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from edge_hub.event_stream import EventFanout
from edge_hub.events import Event


def private_event():
    return Event(id='private-id', type='robot_fault', zone='private-zone', at_ms=1,
                 severity='notice', details={'secret': 'private-details'})


def test_fanout_counts_are_fixed_aggregate_and_not_delivery_ack():
    async def scenario():
        hub = EventFanout(queue_size=1, max_clients=2)
        hub.publish(private_event())  # Count publication even without subscribers.
        slow, healthy = hub.subscribe(), hub.subscribe()
        assert hub.subscribe() is None
        hub.publish(private_event())
        healthy.queue.get_nowait()
        hub.publish(private_event())  # Only slow overflows.
        healthy.queue.get_nowait()
        hub.publish(private_event())  # Already-overflowed slow is not counted twice.
        report = hub.snapshot()
        assert report['published_events'] == 4
        assert report['enqueued_notifications'] == 4
        assert report['overflowed_clients'] == 1 and report['rejected_connections'] == 1
        assert report['active_subscriptions'] == 2
        assert report['queue_capacity_per_client'] == 1 and report['client_limit'] == 2
        assert 'not delivery ACK' in report['scope']
        assert 'private' not in json.dumps(report)
        hub.unsubscribe(slow)
        hub.unsubscribe(healthy)
        hub.unsubscribe(slow)  # Idempotent cleanup is not a negative gauge.
        report['published_events'] = -100
        assert hub.snapshot()['active_subscriptions'] == 0
        assert hub.snapshot()['published_events'] == 4
    asyncio.run(scenario())


@pytest.mark.parametrize('stage', ['private-label', '', 'send_timeouts'])
def test_untrusted_timeout_labels_cannot_expand_metrics(stage):
    hub = EventFanout()
    before = hub.snapshot()
    with pytest.raises(ValueError):
        hub.record_timeout(stage)
    assert hub.snapshot() == before


def test_worker_thread_snapshots_do_not_race_loop_publication():
    async def scenario():
        hub = EventFanout(queue_size=1)
        subscriber = hub.subscribe()
        keys = set(hub.snapshot())
        with ThreadPoolExecutor(max_workers=1) as executor:
            reads = executor.submit(lambda: [hub.snapshot() for _ in range(500)])
            for _ in range(500):
                hub.publish(private_event())
            reports = reads.result(timeout=2)
        assert all(set(report) == keys and report['active_subscriptions'] == 1
                   for report in reports)
        assert hub.snapshot()['published_events'] == 500
        assert hub.snapshot()['overflowed_clients'] == 1
        hub.unsubscribe(subscriber)
    asyncio.run(scenario())


def test_fanout_diagnostics_remain_operator_only_and_no_store(monkeypatch):
    hub = importlib.import_module('edge_hub.app')
    fanout = EventFanout()
    fanout.publish(private_event())
    monkeypatch.setattr(hub, 'event_fanout', fanout)
    monkeypatch.setattr(hub, 'OPERATOR_KEY', 'metrics-fixture-operator')
    client = TestClient(hub.app)
    assert client.get('/api/v1/diagnostics/metrics').status_code == 403
    assert client.get('/api/v1/diagnostics/metrics', headers={
        'X-Event-Ingest-Key': 'collector'}).status_code == 403
    response = client.get('/api/v1/diagnostics/metrics', headers={
        'X-Operator-Key': 'metrics-fixture-operator'})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json()['event_websocket']['published_events'] == 1
    assert 'private-' not in response.text and 'metrics-fixture' not in response.text
    assert 'total_requests' in response.json()  # Existing HTTP schema is retained.
