import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest
import test_cloud_bootstrap
import test_cloud_google_identity
from fastapi.testclient import TestClient
from test_cloud_profile_provenance import api_manifest

from deploy.cloud import host, managed_stage
from deploy.cloud.bootstrap import open_services
from deploy.cloud.google_identity import GoogleIdentityVerifier
from deploy.cloud.http_app import create_app

prepared = test_cloud_bootstrap.prepared
seeded = test_cloud_bootstrap.seeded
keys = test_cloud_google_identity.keys
ORIGIN = 'https://synthetic-stage.onrender.com'
SERVICE = 'srv-synthetic1234567890'


def metadata(root):
    value = {'format': 'neighbour-managed-stage-v1', 'service_id': SERVICE, 'origin': ORIGIN,
        'google_client_id': test_cloud_google_identity.CLIENT,
        'accounts': {'staff-subject': 'staff'}, 'database_profile': api_manifest()}
    env = {'RENDER_SERVICE_ID': SERVICE, 'RENDER_EXTERNAL_URL': ORIGIN,
        'NEIGHBOUR_CREDENTIAL_BACKEND': 'managed-environment',
        'NEIGHBOUR_SETTINGS_ROOT': str(root / 'settings'),
        'NEIGHBOUR_CLOUD_CONFIG': str(root / 'metadata/host.json')}
    return value, env


def test_explicit_managed_boot_recreates_only_metadata_and_never_copies_secrets(tmp_path):
    root = tmp_path / 'stage'
    value, env = metadata(root)
    env['NEIGHBOUR_SECRET_TURSO_DATA'] = 'PRIVATE-SYNTHETIC-KEY'
    path = managed_stage.provision(json.dumps(value), environment=env, root=root)
    config = json.loads(path.read_text())
    assert config['accounts'] == {'staff-subject': 'staff'}
    assert config['runtime_root'] == str(root / 'runtime')
    assert not list((root / 'runtime').iterdir()) and not list((root / 'settings').iterdir())
    assert b'PRIVATE' not in path.read_bytes()
    assert managed_stage.provision(json.dumps(value), environment=env, root=root) == path
    assert len(list((root / 'metadata').iterdir())) == 2
    path.write_bytes(b'KEEP-EXISTING-METADATA')
    with pytest.raises(ValueError, match='managed_stage_configuration_required'):
        managed_stage.provision(json.dumps(value), environment=env, root=root)
    assert path.read_bytes() == b'KEEP-EXISTING-METADATA'


@pytest.mark.parametrize('key,value', [('RENDER_SERVICE_ID', 'srv-other1234567890'),
    ('RENDER_EXTERNAL_URL', 'https://other.onrender.com'), ('NEIGHBOUR_CREDENTIAL_BACKEND', ''),
    ('NEIGHBOUR_SETTINGS_ROOT', '/unreviewed'), ('NEIGHBOUR_CLOUD_CONFIG', '/unreviewed'),
    ('NEIGHBOUR_SECRET_CLOUDFLARE_GEMMA', 'PRIVATE'), ('NEIGHBOUR_SECRET_AZURE_SPEECH_F0', 'PRIVATE'),
    ('NEIGHBOUR_SECRET_TAVILY', 'PRIVATE')])
def test_wrong_service_paths_or_real_model_credentials_reject_before_writing(tmp_path, key, value):
    root = tmp_path / 'stage'
    config, env = metadata(root)
    env[key] = value
    with pytest.raises(ValueError):
        managed_stage.provision(json.dumps(config), environment=env, root=root)
    assert not root.exists()


def test_duplicate_fields_unknown_mode_or_staffless_account_cannot_activate(tmp_path):
    root = tmp_path / 'stage'
    config, env = metadata(root)
    for changed in ({**config, 'format': 'production'}, {**config, 'accounts': {'resident': 'resident'}},
                    {**config, 'extra': 'PRIVATE'}):
        with pytest.raises(ValueError):
            managed_stage.provision(json.dumps(changed), environment=env, root=root)
    with pytest.raises(ValueError):
        managed_stage.provision('{"format":"x","format":"y"}', environment=env, root=root)
    old = copy.deepcopy(config)
    old['database_profile']['format'] = 'neighbour-cloud-storage-v1'
    with pytest.raises(ValueError):
        managed_stage.provision(json.dumps(old), environment=env, root=root)


def test_managed_factory_selects_acceptance_without_opening_database(tmp_path, monkeypatch):
    root = tmp_path / 'stage'
    config, env = metadata(root)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(managed_stage.VARIABLE, json.dumps(config))
    original = managed_stage.provision
    monkeypatch.setattr(managed_stage, 'provision', lambda value: original(value, root=root))
    monkeypatch.setattr(host, 'open_services', lambda *a, **kw: pytest.fail('no DB before lifespan'))
    candidate = host.create_host()
    assert candidate.storage_acceptance and candidate.application is None
    assert candidate.config.origin == ORIGIN


def test_ingress_diagnostic_only_exposes_network_class_and_never_credentials():
    app = host.CloudHost(SimpleNamespace(origin=ORIGIN), storage_acceptance=True)
    messages = []

    async def run():
        async def send(message):
            messages.append(message)
        async def receive():
            return {'type': 'http.request', 'body': b''}
        scope = {'type': 'http', 'method': 'GET', 'path': '/health/ingress', 'scheme': 'http',
            'client': ('10.123.45.6', 1234), 'headers': [(b'host', b'synthetic-stage.onrender.com'),
            (b'x-forwarded-proto', b'https'), (b'authorization', b'Bearer PRIVATE'),
            (b'x-forwarded-for', b'PRIVATE-IP')]}
        await app(scope, receive, send)
    asyncio.run(run())
    content = b''.join(message.get('body', b'') for message in messages)
    result = json.loads(content)
    assert result['peer_network'] == '10.0.0.0/8' and result['single_forwarded_https']
    assert result['public_ready'] is False
    assert b'PRIVATE' not in content and b'10.123.45.6' not in content


def test_stage_serves_only_public_login_metadata_and_blocks_all_mutations(seeded, keys):
    services = open_services(seeded[0], signing_key_loader=lambda: test_cloud_bootstrap.KEY)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={'keys': [keys[1]]}, headers={'cache-control': 'max-age=300'})))
    verifier = GoogleIdentityVerifier(test_cloud_google_identity.CLIENT, {'staff-subject': 'staff'}, client=client)
    before = test_cloud_bootstrap.contents(seeded[0])
    try:
        app = create_app(services, verifier, origin=ORIGIN, storage_acceptance=True)
        headers = {'Authorization': 'Bearer ' + test_cloud_google_identity.token(keys), 'Origin': ORIGIN}
        with TestClient(app, base_url=ORIGIN) as browser:
            assert browser.get('/').status_code == 200
            public = browser.get('/login-config')
            assert public.json() == {'client_id': test_cloud_google_identity.CLIENT}
            assert 'staff-subject' not in public.text
            assert browser.get('/stage-login.js').status_code == 200
            assert browser.get('/api/v1/resident/session').status_code == 401
            identity = browser.get('/api/v1/resident/session', headers=headers)
            assert identity.json() == {'authenticated': True, 'role': 'staff', 'storage_acceptance': True}
            for route in ('/api/v1/resident/chat', '/api/v1/resident/model/v1/chat/completions',
                          '/_audio/v1/audio/resident-stream', '/api/v1/service-desk/requests'):
                response = browser.post(route, headers=headers, json={})
                assert response.status_code == 423
            assert browser.get('/api/v1/ep/fleet', headers=headers).status_code == 404
        assert before == test_cloud_bootstrap.contents(seeded[0])
    finally:
        services.close()
        asyncio.run(client.aclose())
