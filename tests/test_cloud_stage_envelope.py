import base64
import copy
import json

import pytest
import test_cloud_managed_stage

from deploy.cloud import host, managed_stage, stage_envelope

KEY = 'SYNTHETIC-BOOTSTRAP-ONLY-NOT-A-SERVICE-KEY'
SERVICE = test_cloud_managed_stage.SERVICE
ORIGIN = test_cloud_managed_stage.ORIGIN


def values(root):
    metadata, env = test_cloud_managed_stage.metadata(root)
    return {**{k: v for k, v in env.items() if not k.startswith('RENDER_')},
        'NEIGHBOUR_MANAGED_STAGE': json.dumps(metadata),
        'NEIGHBOUR_SECRET_TURSO_DATA': 'NEW-SYNTHETIC-WRITER',
        'NEIGHBOUR_SECRET_TURSO_READ': 'NEW-SYNTHETIC-READER',
        'NEIGHBOUR_SECRET_RETENTION_LEDGER': 'base64:' + base64.b64encode(b'a' * 32).decode('ascii')}


def test_authenticated_envelope_contains_no_plaintext_configuration(tmp_path):
    data = values(tmp_path / 'stage')
    sealed = stage_envelope.seal(data, KEY, service_id=SERVICE, origin=ORIGIN)
    assert 'NEW-SYNTHETIC' not in sealed and 'staff-subject' not in sealed
    assert stage_envelope.open_envelope(sealed, KEY, service_id=SERVICE, origin=ORIGIN) == data
    assert stage_envelope.seal(data, KEY, service_id=SERVICE, origin=ORIGIN) != sealed


@pytest.mark.parametrize('changed', ['key', 'service', 'origin', 'ciphertext', 'duplicate', 'large'])
def test_wrong_binding_or_modified_envelope_fails_without_values_in_error(tmp_path, changed):
    sealed = stage_envelope.seal(values(tmp_path / 'stage'), KEY, service_id=SERVICE, origin=ORIGIN)
    key, service, origin = KEY, SERVICE, ORIGIN
    if changed == 'key':
        key = 'OTHER-SYNTHETIC-BOOTSTRAP-KEY'
    elif changed == 'service':
        service = 'srv-other123456789012'
    elif changed == 'origin':
        origin = 'https://other.onrender.com'
    elif changed == 'ciphertext':
        data = json.loads(sealed)
        data['ciphertext'] = ('A' if data['ciphertext'][0] != 'A' else 'B') + data['ciphertext'][1:]
        sealed = json.dumps(data)
    elif changed == 'duplicate':
        sealed = sealed[:-1] + ',"format":"other"}'
    else:
        sealed = 'X' * 100_000
    with pytest.raises(ValueError, match='^stage_envelope_unavailable$'):
        stage_envelope.open_envelope(sealed, key, service_id=service, origin=origin)


def test_envelope_cannot_supply_model_keys_or_change_forwarding_trust(tmp_path):
    data = values(tmp_path / 'stage')
    for extra in ('NEIGHBOUR_SECRET_AZURE_SPEECH_F0', 'FORWARDED_ALLOW_IPS'):
        with pytest.raises(ValueError):
            stage_envelope.seal({**data, extra: '*'}, KEY, service_id=SERVICE, origin=ORIGIN)


def test_factory_validates_before_installing_secrets_and_never_opens_database(tmp_path, monkeypatch):
    root = tmp_path / 'stage'
    data = values(root)
    for key in stage_envelope.KEYS:
        monkeypatch.setenv(key, '')
    for key, value in {'RENDER_SERVICE_ID': SERVICE, 'RENDER_EXTERNAL_URL': ORIGIN,
                       'NEIGHBOUR_SECRET_TURSO_DATA': KEY}.items():
        monkeypatch.setenv(key, value)
    sealed = stage_envelope.seal(data, KEY, service_id=SERVICE, origin=ORIGIN)
    monkeypatch.setenv(stage_envelope.VARIABLE, sealed)
    original = managed_stage.provision
    monkeypatch.setattr(managed_stage, 'provision', lambda value, **kw: original(value, root=root, **kw))
    monkeypatch.setattr(host, 'open_services', lambda *a, **kw: pytest.fail('no DB at factory'))
    candidate = host.create_host()
    assert candidate.storage_acceptance
    assert host.os.environ['NEIGHBOUR_SECRET_TURSO_DATA'] == data['NEIGHBOUR_SECRET_TURSO_DATA']
    assert not list((root / 'runtime').iterdir())


def test_invalid_stage_metadata_leaves_old_environment_and_files_untouched(tmp_path, monkeypatch):
    root = tmp_path / 'stage'
    data = copy.deepcopy(values(root))
    metadata = json.loads(data['NEIGHBOUR_MANAGED_STAGE'])
    metadata['accounts'] = {'resident': 'resident'}
    data['NEIGHBOUR_MANAGED_STAGE'] = json.dumps(metadata)
    monkeypatch.setenv('RENDER_SERVICE_ID', SERVICE)
    monkeypatch.setenv('RENDER_EXTERNAL_URL', ORIGIN)
    monkeypatch.setenv('NEIGHBOUR_SECRET_TURSO_DATA', KEY)
    monkeypatch.setenv(stage_envelope.VARIABLE,
                       stage_envelope.seal(data, KEY, service_id=SERVICE, origin=ORIGIN))
    original = managed_stage.provision
    monkeypatch.setattr(managed_stage, 'provision', lambda value, **kw: original(value, root=root, **kw))
    with pytest.raises(ValueError):
        host.create_host()
    assert host.os.environ['NEIGHBOUR_SECRET_TURSO_DATA'] == KEY
    assert not root.exists()
