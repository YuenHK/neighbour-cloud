import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from starlette.concurrency import run_in_threadpool

from deploy.cloud.database_profile import ROLE_FILES, DatabaseProfile
from deploy.cloud.runtime_storage import RuntimeStorage, StorageMiddleware
from deploy.cloud.state_store import StateStore
from edge_hub import azure_voice, cloudflare_gemma, patrol_cloud
from edge_hub.approved_photo import ApprovedPhoto
from edge_hub.cloud_allowance import CloudAllowance
from edge_hub.cloud_credentials import settings_root
from edge_hub.control_state import read_control
from edge_hub.quota_overview import overview
from edge_hub.resident_cloud import CloudUnavailable
from edge_hub.storage_context import current_storage, use_storage
from edge_hub.usage_snapshot import usage_snapshot

VOICE = 'azure-voice-control.json'
STOP = 'cloudflare-gemma-quota-stop.json'
COOLDOWN = 'cloudflare-gemma-cooldown.json'


def imported_controls():
    return {VOICE: {'paused': False}, STOP: {'until': '2000-01-01T00:00:00+00:00'},
            COOLDOWN: {'until': '2000-01-01T00:00:00+00:00', 'reason': 'network'}}


@pytest.fixture(params=['sqlite', 'libsql'])
def cloud(tmp_path, request, monkeypatch):
    runtime, settings, remote = (tmp_path / name for name in ('runtime', 'settings', 'remote'))
    for folder in (runtime, settings, remote):
        folder.mkdir()
    native = sqlite3 if request.param == 'sqlite' else pytest.importorskip('libsql')
    endpoints = {role: 'libsql://synthetic-' + role.replace('_', '-') + '.turso.io' for role in ROLE_FILES}
    roles = {url: role for role, url in endpoints.items()}

    def connect(url, **kwargs):
        assert kwargs['auth_token'] == 'synthetic-test-token'
        path = remote / (roles[url] + '.sqlite3')
        if request.param == 'sqlite':
            return native.connect(path, timeout=kwargs['timeout'], check_same_thread=False)
        return native.connect(str(path), timeout=kwargs['timeout'], _check_same_thread=False)

    manifest = {'format': 'neighbour-cloud-storage-v1', 'provider': 'turso-libsql', 'plan': 'Free',
                'ui_verified': True, 'mode': 'remote-primary',
                'databases': {role: {'url': url, 'credential': 'turso-data-token'} for role, url in endpoints.items()}}
    profile = DatabaseProfile(manifest, runtime_root=runtime, settings_root=settings,
                              secret_loader=lambda: b'synthetic-test-token',
                              driver_loader=lambda: SimpleNamespace(Error=native.Error, connect=connect))
    db = profile.connect(settings / 'cloud-control.sqlite3', check_same_thread=False)
    controls = StateStore(db, initialize=True)
    controls.seed(imported_controls())
    # Explicit migration-stage creation, outside the runtime scope.
    CloudAllowance(settings / 'cloud-usage.sqlite3', connection_factory=profile.connect)
    storage = RuntimeStorage(profile, controls)
    (settings / 'azure-speech-f0.json').write_text(json.dumps({'sku': 'F0', 'region': 'eastasia'}))
    (settings / 'azure-speech-f0-key.dpapi').write_bytes(b'synthetic-key-reference')
    (settings / 'cloudflare-gemma-free.json').write_text(json.dumps(
        {'enabled': True, 'plan': 'Free', 'ui_verified': True, 'account_id': 'a' * 32}))
    (settings / 'cloudflare-gemma-key.dpapi').write_bytes(b'synthetic-key-reference')
    monkeypatch.setattr(azure_voice, '_crypt', lambda *a, **k: b'synthetic')
    monkeypatch.setattr(cloudflare_gemma, '_crypt', lambda *a, **k: b'synthetic')
    monkeypatch.setattr(cloudflare_gemma, '_busy', False)
    monkeypatch.setattr(cloudflare_gemma, '_until', 0)
    try:
        yield storage, settings, remote
    finally:
        db.close()


def test_durable_controls_reopen_no_overwrite_and_atomic_import(cloud):
    storage, settings, _ = cloud
    controls = storage.controls
    controls.write(VOICE, {'paused': True})
    reopened = storage.connect(settings / 'cloud-control.sqlite3')
    try:
        assert StateStore(reopened).read(VOICE) == {'paused': True}
    finally:
        reopened.close()
    with pytest.raises(ValueError, match='overwrite'):
        controls.seed({VOICE: {'paused': False}})
    controls.db.execute('DELETE FROM cloud_state WHERE name=?', (COOLDOWN,))
    controls.db.commit()
    with pytest.raises(ValueError, match='overwrite'):
        controls.seed({COOLDOWN: imported_controls()[COOLDOWN], VOICE: {'paused': False}})
    with pytest.raises(OSError):
        controls.read(COOLDOWN)
    assert controls.read(VOICE) == {'paused': True}


def test_missing_and_corrupt_cloud_controls_never_unpause(cloud):
    storage, _, _ = cloud
    with use_storage(storage):
        assert not azure_voice.status()['paused']
        for payload in ('{"paused":"false"}', 'null', '{}', '{broken'):
            storage.controls.db.execute('UPDATE cloud_state SET payload=? WHERE name=?', (payload, VOICE))
            storage.controls.db.commit()
            assert azure_voice.status()['paused']
            with pytest.raises(ValueError):
                azure_voice.synthesize('公開句子', client=object())
        storage.controls.db.execute('DELETE FROM cloud_state WHERE name=?', (VOICE,))
        storage.controls.db.commit()
        assert azure_voice.status()['blocked']
        with pytest.raises(OSError):
            azure_voice.set_paused(False)


def test_state_init_and_active_block_cannot_be_silently_reset(cloud):
    storage, _, _ = cloud
    controls = storage.controls
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    controls.write(STOP, {'until': future})
    with pytest.raises(ValueError, match='shorten'):
        controls.write(STOP, imported_controls()[STOP])
    assert controls.read(STOP) == {'until': future}
    with pytest.raises(ValueError):
        controls.write(VOICE, {'paused': 0})
    controls.db.execute('CREATE TABLE unreviewed(value TEXT)')
    controls.db.commit()
    with pytest.raises(ValueError, match='initialization_or_review'):
        StateStore(controls.db, initialize=True)


def test_quota_status_reads_real_remote_without_local_marker_and_pause_keeps_counts(cloud):
    storage, settings, _ = cloud
    with use_storage(storage):
        assert settings_root() == settings
        CloudAllowance(settings / 'cloud-usage.sqlite3').reserve(
            {'azure_tts_characters': 123, 'cloudflare_gemma_neuron_reservations': 456})
        assert azure_voice.status()['used'] == 123
        assert azure_voice.set_paused(True)['used'] == 123
        assert azure_voice.set_paused(False)['used'] == 123
        rows = overview({'status': 'unavailable', 'data': None}, voice_configured=True)['rows']
        rows = {row['id']: row for row in rows}
        assert rows['azure-voice']['guard']['counters'][0]['used'] == 123
        assert rows['cloudflare-gemma']['guard']['counters'][0]['used'] == 456
    assert not (settings / 'cloud-usage.sqlite3').exists()
    assert not (settings / VOICE).exists()
    assert current_storage() is None


def test_missing_remote_usage_never_creates_zero_ledger_or_dispatches(cloud):
    storage, settings, _ = cloud
    db = storage.connect(settings / 'cloud-usage.sqlite3')
    db.execute('DROP TABLE usage')
    db.commit()
    db.close()
    with use_storage(storage):
        assert usage_snapshot(settings / 'cloud-usage.sqlite3', ('2026-10',)) is None
        status = azure_voice.status()
        assert status['used'] is None and status['remaining'] is None and status['blocked']
        with pytest.raises(ValueError):
            azure_voice.synthesize('公開句子', client=object())
        with pytest.raises(sqlite3.Error):
            CloudAllowance(settings / 'cloud-usage.sqlite3')
    db = storage.connect(settings / 'cloud-usage.sqlite3')
    assert db.execute("SELECT name FROM sqlite_master WHERE name='usage'").fetchone() is None
    db.close()
    assert not (settings / 'cloud-usage.sqlite3').exists()


def test_remote_failure_does_not_fall_back_to_local_zero(cloud):
    storage, settings, _ = cloud
    failing = SimpleNamespace(settings_root=settings, controls=storage.controls,
                              connect=lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError('unavailable')))
    with use_storage(failing):
        assert azure_voice.status()['used'] is None
        assert azure_voice.status()['blocked']
        assert usage_snapshot(settings / 'cloud-usage.sqlite3', ('2026-10',)) is None
    assert not (settings / 'cloud-usage.sqlite3').exists()


def test_daily_cloud_stop_survives_process_state_reset_before_dispatch(cloud, monkeypatch):
    storage, settings, _ = cloud
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, json={'errors': [{'code': 3036}]})

    async def run():
        with use_storage(storage):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                for _ in range(2):
                    with pytest.raises(CloudUnavailable):
                        await cloudflare_gemma.complete({'messages': [{'role': 'user', 'content': '公開問候'}]},
                                                        prompt='公開角色', client=client)
                    monkeypatch.setattr(cloudflare_gemma, '_until', 0)
            assert datetime.fromisoformat(read_control(settings, STOP)['until']) > datetime.now(UTC)
            assert cloudflare_gemma.cooling()
    asyncio.run(run())
    assert len(calls) == 1
    assert not (settings / STOP).exists() and not (settings / COOLDOWN).exists()


def test_cloud_cooldown_missing_or_unreadable_fails_before_reservation(cloud):
    storage, settings, _ = cloud
    storage.controls.db.execute('DELETE FROM cloud_state WHERE name=?', (COOLDOWN,))
    storage.controls.db.commit()

    async def run():
        with use_storage(storage):
            assert cloudflare_gemma.state()['cooldown']
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail('no network'))) as client:
                with pytest.raises(CloudUnavailable):
                    await cloudflare_gemma.complete({'messages': [{'role': 'user', 'content': '公開問候'}]},
                                                    prompt='公開角色', client=client)
            day = datetime.now(UTC).strftime('%Y-%m-%d')
            assert usage_snapshot(settings / 'cloud-usage.sqlite3', (day,)) == {}
    asyncio.run(run())


def test_missing_cloud_stop_never_uses_local_unblocked_file(cloud):
    storage, settings, _ = cloud
    # A stale Render filesystem must not override the authoritative remote flag.
    (settings / STOP).write_text(json.dumps(imported_controls()[STOP]))
    storage.controls.db.execute('DELETE FROM cloud_state WHERE name=?', (STOP,))
    storage.controls.db.commit()

    async def run():
        with use_storage(storage):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail('no network'))) as client:
                with pytest.raises(CloudUnavailable):
                    await cloudflare_gemma.complete({'messages': [{'role': 'user', 'content': '公開問候'}]},
                                                    prompt='公開角色', client=client)
            day = datetime.now(UTC).strftime('%Y-%m-%d')
            assert usage_snapshot(settings / 'cloud-usage.sqlite3', (day,)) == {}
    asyncio.run(run())
    assert json.loads((settings / STOP).read_text()) == imported_controls()[STOP]


def test_cloud_failure_records_persistence_problem_without_leaking_or_hanging_busy(cloud, monkeypatch):
    storage, _, _ = cloud
    original = storage.controls.write

    def write(name, value):
        if name == COOLDOWN:
            raise sqlite3.OperationalError('synthetic private upstream data')
        return original(name, value)
    monkeypatch.setattr(storage.controls, 'write', write)

    async def run():
        with use_storage(storage):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
                with pytest.raises(CloudUnavailable):
                    await cloudflare_gemma.complete({'messages': [{'role': 'user', 'content': '公開問候'}]},
                                                    prompt='公開角色', client=client)
            assert not cloudflare_gemma._busy
            detail = cloudflare_gemma.state()['last_failure_detail']
            assert detail['control_persistence'] == 'unavailable'
            assert 'private' not in json.dumps(detail)
    asyncio.run(run())


def test_patrol_quota_stop_uses_same_durable_controls(cloud, monkeypatch):
    storage, settings, _ = cloud
    monkeypatch.setattr(patrol_cloud, '_crypt', lambda *a, **k: b'synthetic')
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429)
    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(patrol_cloud.httpx, 'Client', lambda **kwargs: client)
    photo = ApprovedPhoto(b'generated-masked-photo', 'a' * 64, 'b' * 64)
    with use_storage(storage):
        assert patrol_cloud.review(photo, {'litter'})[1] == 'quota_exhausted'
        assert patrol_cloud.review(photo, {'litter'})[1] == 'quota_exhausted'
        with pytest.raises(ValueError):
            cloudflare_gemma.reserve([{'content': '公開文字'}])
    assert len(calls) == 1 and not (settings / STOP).exists()


def test_scope_reaches_sync_worker_and_stream_and_resets_on_error(cloud):
    storage, settings, _ = cloud
    app = FastAPI()

    @app.get('/sync')
    def sync():
        return {'settings': str(settings_root()), 'scoped': current_storage() is storage}

    @app.get('/stream')
    async def stream():
        async def chunks():
            assert current_storage() is storage
            assert await run_in_threadpool(current_storage) is storage
            yield b'scoped'
        return StreamingResponse(chunks())

    with TestClient(StorageMiddleware(app, storage)) as client:
        assert client.get('/sync').json() == {'settings': str(settings), 'scoped': True}
        assert client.get('/stream').content == b'scoped'
    with pytest.raises(RuntimeError), use_storage(storage):
        raise RuntimeError('test')
    assert current_storage() is None


def test_concurrent_scopes_do_not_leak_between_apps_or_native(cloud):
    storage, settings, _ = cloud
    other = SimpleNamespace(settings_root=settings / 'other', controls=storage.controls, connect=storage.connect)

    async def read_context(value):
        with use_storage(value):
            await asyncio.sleep(.001)
            assert current_storage() is value
            return settings_root()

    async def run():
        results = await asyncio.gather(read_context(storage), read_context(other))
        assert results == [settings, settings / 'other']
    asyncio.run(run())
    assert current_storage() is None


def test_native_absence_remains_zero_but_corrupt_or_excessive_rows_are_unknown(tmp_path):
    path = tmp_path / 'usage.sqlite3'
    assert usage_snapshot(path, ('2026-10',)) == {} and not path.exists()
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE usage(meter TEXT,period TEXT,amount INTEGER)')
    db.execute("INSERT INTO usage VALUES('azure_tts_characters','2026-10',-1)")
    db.commit()
    assert usage_snapshot(path, ('2026-10',)) is None
    with pytest.raises(ValueError, match='persisted'):
        CloudAllowance(path).reserve({'azure_tts_characters': 1}, now=datetime(2026, 10, 29, tzinfo=UTC))
    db.execute('DELETE FROM usage')
    db.executemany("INSERT INTO usage VALUES(?,'2026-10',1)", [(str(i),) for i in range(129)])
    db.commit()
    assert usage_snapshot(path, ('2026-10',)) is None
    db.close()
