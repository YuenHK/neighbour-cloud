import importlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from edge_hub.csv_export import ExportPreparationError, PreparedEventExport
from edge_hub.events import Event, EventStore


def test_capacity_metrics_track_prepared_rejected_and_early_close_without_delivery_claim():
    store = EventStore()
    streams = []
    try:
        streams = [PreparedEventExport(store), PreparedEventExport(store)]
        with pytest.raises(ExportPreparationError):
            PreparedEventExport(store)
        metrics = store.export_metrics()
        assert metrics['active'] == metrics['snapshot_limit'] == metrics['prepared_total'] == 2
        assert metrics['rejected_total'] == 1 and metrics['failed_total'] == 0
        assert 'not delivery ACK' in metrics['scope']
        metrics['active'] = 999  # Returned dictionaries never mutate internal counters.
        streams[0].close()
        streams[0].close()
        assert store.export_metrics()['active'] == 1
        list(streams[1])
        assert store.export_metrics()['active'] == 0
        assert store.export_metrics()['failed_total'] == 0
    finally:
        for stream in streams:
            stream.close()
        store.close()


def test_preparation_and_consumer_failures_are_counted_without_private_values(monkeypatch):
    from edge_hub import events

    store = EventStore()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(events.tempfile, 'TemporaryDirectory',
                          lambda **kw: (_ for _ in ()).throw(OSError('PRIVATE_PATH')))
            with pytest.raises(ExportPreparationError):
                PreparedEventExport(store)
        assert store.export_metrics()['failed_total'] == 1
        assert store.export_metrics()['prepared_total'] == 0
        with pytest.raises(RuntimeError), store.export_snapshot():
            raise RuntimeError('PRIVATE_CONSUMER_ERROR')
        metrics = store.export_metrics()
        assert metrics['active'] == 0 and metrics['prepared_total'] == 1
        assert metrics['failed_total'] == 2
        assert 'PRIVATE' not in json.dumps(metrics)
    finally:
        store.close()


def test_threaded_metrics_account_for_all_attempts_without_leaking_active_slots():
    store = EventStore()
    def attempt(_):
        try:
            stream = PreparedEventExport(store)
        except ExportPreparationError:
            return
        stream.close()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(attempt, range(20)))
        metrics = store.export_metrics()
        assert metrics['active'] == metrics['failed_total'] == 0
        assert metrics['prepared_total'] + metrics['rejected_total'] == 20
    finally:
        store.close()


def test_metrics_reset_on_store_recreation_even_when_database_is_retained(tmp_path):
    path = tmp_path / 'events.sqlite3'
    store = EventStore(path)
    PreparedEventExport(store).close()
    assert store.export_metrics()['prepared_total'] == 1
    store.close()
    reopened = EventStore(path)
    try:
        assert reopened.export_metrics()['prepared_total'] == 0
        assert reopened.export_metrics()['active'] == 0
    finally:
        reopened.close()


def test_metrics_are_operator_only_and_contain_no_event_or_credential_content(monkeypatch):
    module = importlib.import_module('edge_hub.app')
    store = EventStore()
    monkeypatch.setattr(module, 'store', store)
    monkeypatch.setattr(module, 'OPERATOR_KEY', 'export-metrics-operator')
    monkeypatch.setattr(module, 'EVENT_INGEST_KEY', 'export-metrics-collector')
    try:
        store.add(Event(id='PRIVATE_ID', zone='PRIVATE_ZONE', type='litter_detected',
                        at_ms=10, severity='notice', details={'note': 'PRIVATE_DETAILS'}))
        client = TestClient(module.app)
        assert client.get('/api/v1/diagnostics/metrics').status_code == 403
        assert client.get('/api/v1/diagnostics/metrics',
                          headers={'X-Event-Ingest-Key': 'export-metrics-collector'}).status_code == 403
        response = client.get('/api/v1/diagnostics/metrics',
                              headers={'X-Operator-Key': 'export-metrics-operator'})
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        metrics = response.json()['event_exports']
        assert set(metrics) == {'active', 'prepared_total', 'rejected_total', 'failed_total',
                                'snapshot_limit', 'scope'}
        assert 'PRIVATE' not in response.text
        assert 'export-metrics-operator' not in response.text
        assert 'export-metrics-collector' not in response.text
    finally:
        store.close()
