import pytest

from edge_hub import cloud_credentials
from edge_hub import cloud_host_credentials as host


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    settings = tmp_path / 'settings'
    settings.mkdir()
    credentials = tmp_path / 'credentials'
    credentials.mkdir()
    monkeypatch.setenv('NEIGHBOUR_CREDENTIAL_BACKEND', 'systemd')
    monkeypatch.setenv('NEIGHBOUR_SETTINGS_ROOT', str(settings))
    monkeypatch.setenv('CREDENTIALS_DIRECTORY', str(credentials))
    return settings, credentials


def test_default_windows_settings_path_remains_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv('NEIGHBOUR_CREDENTIAL_BACKEND', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setenv('NEIGHBOUR_SETTINGS_ROOT', '/ignored-without-explicit-opt-in')
    assert cloud_credentials.settings_root() == tmp_path / 'ZhiweiJianbing'


@pytest.mark.parametrize('name', sorted(host.NAMES))
def test_explicit_cloud_backend_reads_only_named_secret(cloud, name):
    settings, credentials = cloud
    (credentials / name).write_bytes(b'synthetic-public-test-key\n')
    marker = host.reference(name)
    assert b'synthetic' not in marker
    assert cloud_credentials.settings_root() == settings
    assert cloud_credentials._crypt(marker, decrypt=True) == b'synthetic-public-test-key'
    with pytest.raises(RuntimeError, match='provisioned outside'):
        cloud_credentials._crypt(b'not-a-secret', decrypt=False)


@pytest.mark.parametrize('data', [b'', b'Windows-DPAPI-blob', host.PREFIX + b'../token',
                                host.PREFIX + b'azure-speech-f0-key\n', host.PREFIX + b'\xff'])
def test_cloud_does_not_accept_dpapi_plaintext_or_path_injection(cloud, data):
    with pytest.raises(RuntimeError):
        cloud_credentials._crypt(data, decrypt=True)


@pytest.mark.parametrize('data', [b'', b'x' * 4097, b'line-one\nline-two', b'\xff'])
def test_invalid_credential_fails_without_echoing_value(cloud, data):
    _, credentials = cloud
    (credentials / 'azure-speech-f0-key').write_bytes(data)
    with pytest.raises(RuntimeError, match='cannot be read') as caught:
        host.decrypt_reference(host.reference('azure-speech-f0-key'))
    assert 'line-one' not in str(caught.value)


@pytest.mark.parametrize('value', ['', 'relative', '/'])
def test_persistent_settings_must_be_explicit_existing_absolute(cloud, monkeypatch, value):
    monkeypatch.setenv('NEIGHBOUR_SETTINGS_ROOT', value)
    with pytest.raises(RuntimeError):
        cloud_credentials.settings_root()


def test_missing_credentials_directory_never_borrows_windows_key(cloud, monkeypatch):
    monkeypatch.delenv('CREDENTIALS_DIRECTORY')
    with pytest.raises(RuntimeError):
        host.decrypt_reference(host.reference('cloudflare-gemma-key'))


def test_existing_provider_configuration_can_use_reference_files(cloud):
    import json

    from edge_hub import azure_voice, cloudflare_gemma

    settings, credentials = cloud
    (settings / 'azure-speech-f0.json').write_text(json.dumps({'sku': 'F0', 'region': 'eastasia'}))
    (settings / 'cloudflare-gemma-free.json').write_text(json.dumps({
        'enabled': True, 'plan': 'Free', 'ui_verified': True, 'account_id': 'a' * 32,
    }))
    for name in ('azure-speech-f0-key', 'cloudflare-gemma-key'):
        (settings / (name + '.dpapi')).write_bytes(host.reference(name))
        (credentials / name).write_bytes(b'isolated-provider-test-key')
    assert azure_voice.configured()
    assert cloudflare_gemma.configuration()['plan'] == 'Free'
    assert not azure_voice.status()['blocked']
    (settings / 'azure-voice-control.json').write_text('{"paused":true}')
    assert azure_voice.status()['blocked']
    assert not (settings / 'cloud-usage.sqlite3').exists()


@pytest.mark.parametrize('name', sorted(host.NAMES))
def test_managed_environment_reads_only_allowlisted_reference(cloud, monkeypatch, name):
    monkeypatch.setenv('NEIGHBOUR_CREDENTIAL_BACKEND', 'managed-environment')
    monkeypatch.setenv(host.VARIABLES[name], 'synthetic-managed-key')
    assert cloud_credentials._crypt(host.reference(name, mode='managed-environment'), decrypt=True) == b'synthetic-managed-key'
    with pytest.raises(RuntimeError, match='reference is required'):
        cloud_credentials._crypt(host.reference(name), decrypt=True)
    assert not any(cloud[0].iterdir())


@pytest.mark.parametrize('value', ['', 'private\nkey', 'private key', ' x', '\u4e2d', 'x' * 4097])
def test_bad_managed_environment_does_not_fall_back_or_echo(cloud, monkeypatch, value):
    monkeypatch.setenv('NEIGHBOUR_CREDENTIAL_BACKEND', 'managed-environment')
    monkeypatch.setenv(host.VARIABLES['azure-speech-f0-key'], value)
    with pytest.raises(RuntimeError) as caught:
        host.decrypt_reference(host.reference('azure-speech-f0-key', mode='managed-environment'))
    assert str(caught.value) == 'Private service credential cannot be read'


def test_unknown_backend_is_never_silent_default(monkeypatch):
    monkeypatch.setenv('NEIGHBOUR_CREDENTIAL_BACKEND', 'systemd-typo')
    with pytest.raises(RuntimeError, match='Unsupported credential backend'):
        cloud_credentials.settings_root()
