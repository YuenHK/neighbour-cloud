import asyncio
import hashlib
import hmac
import json
import threading
import time
from types import SimpleNamespace

import pytest
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from deploy.cloud import rollout

KEY = b'synthetic-rollout-key-only-0000000'


def receipt(**changes):
    value = {'format': 'neighbour-stopped-writer-v1', 'release': rollout.RELEASE,
        'service_id': rollout.SERVICE, 'stop_event_id': 'evt-synthetic',
        'stopped_instance': rollout.SERVICE + '-synthetic',
        'stopped_at_utc': '2026-10-31T05:00:00+00:00',
        'approved_utc': '2026-10-31T05:01:00+00:00'}
    value.update(changes)
    value['signature'] = hmac.new(KEY, rollout.DOMAIN + rollout.canonical(value), hashlib.sha256).hexdigest()
    return json.dumps(value)


@pytest.mark.parametrize('changes', [
    {'service_id': 'srv-other'}, {'release': 'other-release'}, {'stop_event_id': 'not-an-event'},
    {'stopped_instance': 'other-instance'}, {'approved_utc': '2026-10-31T04:59:00+00:00'},
    {'approved_utc': '2026-10-31T05:01:00'}, {'extra': True},
])
def test_signed_receipt_is_bound_to_explicit_stopped_release(changes):
    assert rollout.approved(receipt(), KEY)
    assert not rollout.approved(receipt(**changes), KEY)


def test_missing_invalid_and_wrong_signatures_fail_closed():
    for raw in ('null', '[]', '{}', 'not-json', receipt().replace('evt-synthetic', 'evt-tampered')):
        assert not rollout.approved(raw, KEY)
    assert not rollout.approved(receipt(), b'other-key')


class Application:
    def __init__(self, fail=False):
        self.starts = self.requests = self.stops = 0
        self.fail = fail

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            assert (await receive())['type'] == 'lifespan.startup'
            self.starts += 1
            if self.fail:
                return await send({'type': 'lifespan.startup.failed', 'message': 'synthetic'})
            await send({'type': 'lifespan.startup.complete'})
            assert (await receive())['type'] == 'lifespan.shutdown'
            self.stops += 1
            return await send({'type': 'lifespan.shutdown.complete'})
        self.requests += 1
        return await JSONResponse({'active': True})(scope, receive, send)


def test_waiting_shell_never_opens_real_application_or_accepts_writes():
    app = Application()
    with TestClient(rollout.RolloutHost(app, lambda: False, interval=.005)) as client:
        for method, path in (('GET', '/health'), ('POST', '/api/v1/chat'), ('POST', '/api/v1/service-cases')):
            response = client.request(method, path, json={})
            assert response.status_code == 503
            assert response.json()['public_ready'] is False
        assert app.starts == app.requests == 0
    assert app.stops == 0


def test_cold_boot_shows_a_waiting_page_but_never_exposes_api_or_ready_early():
    app = Application()
    with TestClient(rollout.RolloutHost(app, lambda: False, interval=.005)) as client:
        page = client.get('/')
        assert page.status_code == 200
        assert page.headers['content-type'].startswith('text/html')
        assert '/cloud/boot-wait.js' in page.text
        assert 'no-store' in page.headers['cache-control']
        assert client.get('/cloud/boot-wait.js').status_code == 200
        assert client.get('/cloud/boot-wait.css').status_code == 200
        for suffix in ('community-state.js', 'community-systems.js', 'community-systems.css', 'community-products.js'):
            reply = client.get('/cloud/' + suffix)
            assert reply.status_code == 200
            assert 'no-store' in reply.headers['cache-control']
        assert 'id="bootSystems"' in page.text
        assert client.get('/health').status_code == 503
        assert client.post('/api/v1/chat', json={}).status_code == 503
        assert client.get('/cloud/admin').status_code == 503
        assert app.starts == app.requests == 0


def test_starting_page_waits_for_actual_application_startup_without_accepting_requests():
    release = threading.Event()

    class SlowApplication(Application):
        async def __call__(self, scope, receive, send):
            if scope['type'] == 'lifespan':
                assert (await receive())['type'] == 'lifespan.startup'
                self.starts += 1
                await asyncio.to_thread(release.wait)
                await send({'type': 'lifespan.startup.complete'})
                assert (await receive())['type'] == 'lifespan.shutdown'
                self.stops += 1
                return await send({'type': 'lifespan.shutdown.complete'})
            return await super().__call__(scope, receive, send)

    app = SlowApplication()
    try:
        with TestClient(rollout.RolloutHost(app, lambda: True, interval=.005)) as client:
            deadline = time.monotonic() + 2
            while not app.starts:
                assert time.monotonic() < deadline
                time.sleep(.005)
            state = client.get('/health')
            assert state.status_code == 503 and state.json()['rollout_phase'] == 'starting'
            assert '/cloud/boot-wait.js' in client.get('/').text
            assert client.post('/api/v1/chat', json={}).status_code == 503
            assert app.requests == 0
            release.set()
            while client.get('/health').status_code == 503:
                assert time.monotonic() < deadline
                time.sleep(.005)
            assert client.get('/').json() == {'active': True}
    finally:
        release.set()
    assert app.starts == app.stops == 1


def test_approval_starts_once_and_uses_real_lifespan_shutdown():
    app = Application()
    allowed = threading.Event()
    with TestClient(rollout.RolloutHost(app, allowed.is_set, interval=.005)) as client:
        assert '/cloud/boot-wait.js' in client.get('/').text
        allowed.set()
        deadline = time.monotonic() + 2
        while client.get('/health').status_code == 503:
            assert time.monotonic() < deadline
            time.sleep(.005)
        assert client.get('/').json() == {'active': True}
        assert app.starts == 1
    assert app.stops == 1


def test_failed_startup_stays_closed_without_repeated_initialization():
    app = Application(fail=True)
    wrapper = rollout.RolloutHost(app, lambda: True, interval=.005)
    with TestClient(wrapper) as client:
        deadline = time.monotonic() + 2
        while not wrapper.failed:
            assert time.monotonic() < deadline
            time.sleep(.005)
        assert client.post('/api/v1/chat', json={}).status_code == 503
        assert app.starts == 1 and app.requests == 0


def test_reader_uses_only_supplier_read_token_and_select(monkeypatch):
    from deploy.cloud import host, libsql_connection
    from edge_hub import cloud_host_credentials as credentials

    seen = []

    class DB:
        def execute(self, sql, parameters):
            seen.append(sql)
            assert sql.startswith('SELECT summary FROM cloud_release_probes')
            assert parameters == (rollout.RECORD,)
            return SimpleNamespace(fetchone=lambda: (receipt(),))

        def close(self):
            pass

    def connect(url, **kwargs):
        assert url == 'libsql://synthetic-backup.turso.io'
        assert kwargs == {'auth_token': 'synthetic-read-token-only', 'timeout': 5}
        return DB()

    driver = SimpleNamespace(connect=connect, Error=RuntimeError)
    import importlib
    original = importlib.import_module
    monkeypatch.setattr(importlib, 'import_module', lambda name: driver if name == 'libsql' else original(name))
    monkeypatch.setattr(libsql_connection, 'Connection', lambda db, error: db)
    monkeypatch.setattr(credentials, 'reference', lambda name, **kwargs: name)
    monkeypatch.setattr(credentials, 'decrypt_reference', lambda name: (
        b'synthetic-read-token-only' if name == 'turso-read-token' else pytest.fail('writer credential requested')))
    monkeypatch.setattr(host, 'ledger_key', lambda: KEY)
    read = rollout.permission_reader(SimpleNamespace(config=SimpleNamespace(backend='managed-environment'),
        release={'backup_url': 'libsql://synthetic-backup.turso.io'}))
    assert read() is True and len(seen) == 1


def test_entry_factory_defers_host_startup(monkeypatch):
    from deploy.cloud import host

    deferred = Application()
    monkeypatch.setattr(host, 'create_host', lambda: deferred)
    monkeypatch.setattr(rollout, 'permission_reader', lambda item: lambda: False)
    result = rollout.create_host()
    assert isinstance(result, rollout.RolloutHost) and deferred.starts == 0
