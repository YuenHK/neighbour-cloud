import json
from types import SimpleNamespace

import pytest

from deploy.cloud import host
from deploy.cloud.release_envelope import KEYS, open_envelope, seal

BOOTSTRAP = 'PUBLIC-SYNTHETIC-OLD-OWNED-HOST-MATERIAL-' + 'x' * 30
SERVICE = 'srv-' + 'a' * 24
ORIGIN = 'https://neighbour.example.onrender.com'


def values():
    data = {name: 'PUBLIC-SYNTHETIC-' + name for name in KEYS}
    data['NEIGHBOUR_CREDENTIAL_BACKEND'] = 'managed-environment'
    return data


def test_release_transfer_is_authenticated_randomised_and_contains_no_plaintext_secrets():
    expected = values()
    one = seal(expected, BOOTSTRAP, service_id=SERVICE, origin=ORIGIN)
    two = seal(expected, BOOTSTRAP, service_id=SERVICE, origin=ORIGIN)
    assert one != two
    assert all(secret not in one for secret in expected.values())
    assert open_envelope(one, BOOTSTRAP, service_id=SERVICE, origin=ORIGIN) == expected


@pytest.mark.parametrize('change', ['key', 'service', 'origin', 'cipher', 'stage_purpose', 'duplicate'])
def test_unauthenticated_wrong_destination_or_wrong_purpose_envelope_never_opens(change):
    value = seal(values(), BOOTSTRAP, service_id=SERVICE, origin=ORIGIN)
    key, service, origin = BOOTSTRAP, SERVICE, ORIGIN
    if change == 'key':
        key += 'wrong'
    elif change == 'service':
        service = 'srv-' + 'b' * 24
    elif change == 'origin':
        origin = 'https://other.onrender.com'
    elif change == 'duplicate':
        value = value[:-1] + ',"format":"neighbour-release-envelope-v1"}'
    else:
        data = json.loads(value)
        if change == 'stage_purpose':
            data['format'] = 'neighbour-stage-envelope-v1'
        else:
            text = data['ciphertext']
            data['ciphertext'] = ('A' if text[0] != 'A' else 'B') + text[1:]
        value = json.dumps(data)
    with pytest.raises(ValueError, match='release_envelope_unavailable'):
        open_envelope(value, key, service_id=service, origin=origin)


def test_no_billing_proxy_policy_or_arbitrary_environment_can_be_transferred():
    for key in ('FORWARDED_ALLOW_IPS', 'RENDER_API_KEY', 'AZURE_BILLING', 'PATH'):
        with pytest.raises(ValueError, match='release_envelope_unavailable'):
            seal({**values(), key: 'override'}, BOOTSTRAP, service_id=SERVICE, origin=ORIGIN)


def test_formal_factory_validates_then_switches_in_memory_and_never_uses_stage_provision(monkeypatch, tmp_path):
    from deploy.cloud import managed_release, managed_stage

    payload = values()
    cipher = seal(payload, BOOTSTRAP, service_id=SERVICE, origin=ORIGIN)
    monkeypatch.setenv('NEIGHBOUR_RELEASE_ENVELOPE', cipher)
    monkeypatch.setenv('NEIGHBOUR_SECRET_TURSO_DATA', BOOTSTRAP)
    monkeypatch.setenv('RENDER_SERVICE_ID', SERVICE)
    monkeypatch.setenv('RENDER_EXTERNAL_URL', ORIGIN)
    monkeypatch.setenv('NEIGHBOUR_STAGE_ENVELOPE', 'old-stage-cipher-only')
    monkeypatch.setenv('NEIGHBOUR_MANAGED_STAGE', 'old-stage-metadata')
    # Register every environment value for cleanup after the real factory's
    # explicit in-memory transition; never affect the native parent process.
    for key in payload:
        if key not in ('NEIGHBOUR_SECRET_TURSO_DATA',):
            monkeypatch.setenv(key, 'SYNTHETIC-ORIGINAL-' + key)
    expected = {'config_path': tmp_path / 'host.json', 'backup_url': 'libsql://formal.turso.io', 'initial_backup_id': 'a' * 32, 'probe_id': 'b' * 64}

    def provision(raw, *, environment):
        assert raw == payload['NEIGHBOUR_MANAGED_RELEASE']
        assert not any(key in environment for key in ('NEIGHBOUR_STAGE_ENVELOPE', 'NEIGHBOUR_MANAGED_STAGE'))
        assert all(environment[key] == value for key, value in payload.items())
        return expected

    monkeypatch.setattr(managed_release, 'provision', provision)
    monkeypatch.setattr(managed_stage, 'provision', lambda *a, **k: pytest.fail('formal must not reuse stage installer'))
    config = SimpleNamespace(verified='synthetic')
    monkeypatch.setattr(host, 'read_configuration', lambda: config)
    result = host.create_host()
    assert result.config is config and result.release == expected and not result.storage_acceptance


def test_failed_formal_provision_leaves_original_stage_environment_untouched(monkeypatch):
    import os

    from deploy.cloud import managed_release

    cipher = seal(values(), BOOTSTRAP, service_id=SERVICE, origin=ORIGIN)
    for key, value in {'NEIGHBOUR_RELEASE_ENVELOPE': cipher, 'NEIGHBOUR_SECRET_TURSO_DATA': BOOTSTRAP,
                       'RENDER_SERVICE_ID': SERVICE, 'RENDER_EXTERNAL_URL': ORIGIN,
                       'NEIGHBOUR_STAGE_ENVELOPE': 'keep-original-stage'}.items():
        monkeypatch.setenv(key, value)

    def refuse(*args, **kwargs):
        raise ValueError('synthetic formal cutover not verified')

    monkeypatch.setattr(managed_release, 'provision', refuse)
    before = dict(os.environ)
    with pytest.raises(ValueError):
        host.create_host()
    assert dict(os.environ) == before
