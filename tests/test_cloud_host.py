import asyncio
import base64
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_cloud_bootstrap
from fastapi.testclient import TestClient

prepared = test_cloud_bootstrap.prepared
seeded = test_cloud_bootstrap.seeded
ORIGIN = 'https://neighbour.example'


def configuration(tmp_path, runtime, settings):
    profile = tmp_path / 'databases.json'
    profile.write_text('{}', encoding='utf-8')
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    value = {'format': 'neighbour-cloud-host-v1', 'origin': ORIGIN,
        'google_client_id': '123456789-synthetic.apps.googleusercontent.com',
        'accounts': {'synthetic-staff': 'staff'}, 'database_profile': str(profile),
        'runtime_root': str(runtime), 'settings_root': str(settings), 'scratch_root': str(scratch)}
    path = tmp_path / 'host.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    return path, value


def environment(monkeypatch, path, settings):
    monkeypatch.setenv('NEIGHBOUR_CLOUD_CONFIG', str(path))
    monkeypatch.setenv('NEIGHBOUR_CREDENTIAL_BACKEND', 'managed-environment')
    monkeypatch.setenv('NEIGHBOUR_SETTINGS_ROOT', str(settings))
    monkeypatch.setenv('NEIGHBOUR_SECRET_RETENTION_LEDGER',
        'base64:' + base64.b64encode(test_cloud_bootstrap.KEY).decode('ascii'))


def test_import_and_missing_configuration_never_open_database_or_credentials(monkeypatch):
    from deploy.cloud import host

    monkeypatch.delenv('NEIGHBOUR_CLOUD_CONFIG', raising=False)
    assembly = monkeypatch.setattr(host, 'open_services', lambda *a, **kw: pytest.fail('opened DB'))
    with pytest.raises(host.HostConfigurationError, match='cloud_host_configuration_required'):
        host.create_host()
    assert assembly is None


@pytest.mark.parametrize('change', [
    {'origin': 'http://neighbour.example'}, {'origin': ORIGIN + '/path'},
    {'origin': 'https://user:password@neighbour.example'}, {'origin': ORIGIN + ':443'},
    {'google_client_id': 'PRIVATE-INVALID-CLIENT'}, {'accounts': {'x': 'admin'}},
    {'accounts': {'x': 'resident'}}, {'api_key': 'PRIVATE-NEVER-RETURN'},
    {'runtime_root': 'relative'},
])
def test_invalid_configuration_is_rejected_before_database_access(tmp_path, monkeypatch, change):
    from deploy.cloud import host

    runtime, settings = tmp_path / 'runtime', tmp_path / 'settings'
    runtime.mkdir()
    settings.mkdir()
    path, value = configuration(tmp_path, runtime, settings)
    path.write_text(json.dumps({**value, **change}), encoding='utf-8')
    environment(monkeypatch, path, settings)
    monkeypatch.setattr(host, 'open_services', lambda *a, **kw: pytest.fail('opened DB'))
    with pytest.raises(host.HostConfigurationError) as error:
        host.create_host()
    assert 'PRIVATE' not in str(error.value) and 'password' not in str(error.value)


def test_duplicate_config_fields_and_native_or_wrong_settings_backend_are_rejected(tmp_path, monkeypatch):
    from deploy.cloud import host

    runtime, settings = tmp_path / 'runtime', tmp_path / 'settings'
    runtime.mkdir()
    settings.mkdir()
    path, value = configuration(tmp_path, runtime, settings)
    environment(monkeypatch, path, settings)
    path.write_text(json.dumps(value)[:-1] + ',"origin":"' + ORIGIN + '"}', encoding='utf-8')
    with pytest.raises(host.HostConfigurationError):
        host.create_host()
    path.write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.delenv('NEIGHBOUR_CREDENTIAL_BACKEND')
    with pytest.raises(host.HostConfigurationError):
        host.create_host()
    monkeypatch.setenv('NEIGHBOUR_CREDENTIAL_BACKEND', 'managed-environment')
    monkeypatch.setenv('NEIGHBOUR_SETTINGS_ROOT', str(runtime))
    with pytest.raises(host.HostConfigurationError):
        host.create_host()


def test_factory_defers_storage_until_lifespan_preserves_data_and_closes(seeded, tmp_path, monkeypatch):
    from deploy.cloud import host

    profile, runtime, settings, _, calls = seeded
    path, _ = configuration(tmp_path, runtime, settings)
    environment(monkeypatch, path, settings)
    before = test_cloud_bootstrap.contents(profile)
    calls.clear()
    opened = []
    original = host.open_services

    def assemble(*args, **kwargs):
        services = original(*args, **kwargs)
        opened.append(services)
        return services

    monkeypatch.setattr(host.DatabaseProfile, 'from_file', lambda *args, **kwargs: profile)
    monkeypatch.setattr(host, 'open_services', assemble)
    app = host.create_host()
    assert calls == [] and opened == []
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get('/health')
        assert response.status_code == 200 and response.json()['public_ready'] is False
        assert client.get('/api/v1/service-desk/requests').status_code == 401
        assert client.get('/robots').status_code == 404
        assert len(opened) == 1 and not opened[0].closed
    assert opened[0].closed and app.application is None
    assert before == test_cloud_bootstrap.contents(profile)
    assert list(runtime.iterdir()) == [] and list(settings.iterdir()) == []


def test_startup_failure_is_redacted_and_never_retries(seeded, tmp_path, monkeypatch):
    from deploy.cloud import host

    _, runtime, settings, _, _ = seeded
    path, _ = configuration(tmp_path, runtime, settings)
    environment(monkeypatch, path, settings)
    attempts = []

    def broken(config):
        attempts.append(1)
        raise RuntimeError('PRIVATE-CONNECTION-TOKEN')

    app = host.create_host()
    monkeypatch.setattr(app, '_assemble', broken)

    async def check():
        for _ in range(2):
            send = AsyncMock()
            with pytest.raises(RuntimeError):
                await app({'type': 'lifespan'}, AsyncMock(return_value={'type': 'lifespan.startup'}), send)
            message = send.call_args.args[0]
            assert message['type'] == 'lifespan.startup.failed' and 'PRIVATE' not in str(message)
        assert attempts == [1]
    asyncio.run(check())


def test_failed_api_assembly_closes_already_opened_services(seeded, tmp_path, monkeypatch):
    from deploy.cloud import host

    profile, runtime, settings, _, _ = seeded
    path, _ = configuration(tmp_path, runtime, settings)
    environment(monkeypatch, path, settings)
    monkeypatch.setattr(host.DatabaseProfile, 'from_file', lambda *args, **kwargs: profile)
    opened = []
    original = host.open_services

    def assemble(*args, **kwargs):
        services = original(*args, **kwargs)
        opened.append(services)
        return services

    monkeypatch.setattr(host, 'open_services', assemble)
    monkeypatch.setattr(host, 'create_app', lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('PRIVATE')))
    app = host.create_host()
    with pytest.raises(RuntimeError, match='cloud_host_startup_unavailable'), TestClient(app, base_url=ORIGIN):
        pytest.fail('startup must fail')
    assert len(opened) == 1 and opened[0].closed


def test_cancelled_startup_waits_for_assembly_and_closes_its_handles(tmp_path, monkeypatch):
    from deploy.cloud import host

    runtime, settings = tmp_path / 'runtime', tmp_path / 'settings'
    runtime.mkdir()
    settings.mkdir()
    path, _ = configuration(tmp_path, runtime, settings)
    environment(monkeypatch, path, settings)
    app = host.create_host()
    entered, release = threading.Event(), threading.Event()
    closed = []

    def assemble(_):
        entered.set()
        assert release.wait(3)
        app._services = SimpleNamespace(close=lambda: closed.append(True))
        return AsyncMock()

    monkeypatch.setattr(app, '_assemble', assemble)

    async def check():
        task = asyncio.create_task(app({'type': 'lifespan'},
            AsyncMock(return_value={'type': 'lifespan.startup'}), AsyncMock()))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed == [True] and app.application is None
    asyncio.run(check())


def test_ledger_key_decodes_original_binary_not_encoded_text(monkeypatch):
    from deploy.cloud.host import HostConfigurationError, ledger_key

    monkeypatch.setenv('NEIGHBOUR_CREDENTIAL_BACKEND', 'managed-environment')
    binary = bytes(range(32))
    monkeypatch.setenv('NEIGHBOUR_SECRET_RETENTION_LEDGER', 'base64:' + base64.b64encode(binary).decode())
    assert ledger_key() == binary
    for invalid in ('x' * 32, 'base64:invalid!', 'base64:eA=='):
        monkeypatch.setenv('NEIGHBOUR_SECRET_RETENTION_LEDGER', invalid)
        with pytest.raises(HostConfigurationError):
            ledger_key()
