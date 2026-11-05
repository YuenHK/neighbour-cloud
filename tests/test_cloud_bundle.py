import hashlib
import json
import zipfile

import pytest

from tools.cloud_bundle import build
from tools.cloud_preflight import report


def project(tmp_path):
    root = tmp_path / 'project'
    (root / 'edge_hub/static').mkdir(parents=True)
    (root / 'edge_hub/app.py').write_text('synthetic application source')
    (root / 'edge_hub/static/resident.js').write_text('synthetic UI')
    return root


def test_bundle_is_source_only_and_hashes_match(tmp_path):
    root = project(tmp_path)
    for name in ('.runtime/private.sqlite3', '.env', 'data/events/resident.jpg',
                 'edge_hub/secret.dpapi', 'edge_hub/node_modules/private.js',
                 'edge_hub/__pycache__/private.py', 'edge_hub/secret.key'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('PRIVATE-TEST-MARKER')
    archive = tmp_path / 'bundle.zip'
    result = build(root, archive)
    assert not result['deployed']
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == result['sha256']
    with zipfile.ZipFile(archive) as stored:
        assert set(stored.namelist()) == {'edge_hub/app.py', 'edge_hub/static/resident.js', 'CLOUD-BUNDLE.json'}


def test_cloud_login_source_assets_are_bundled_but_encrypted_setup_is_not(tmp_path):
    root = project(tmp_path)
    assets = root / 'deploy/cloud/login-setup'
    assets.mkdir(parents=True)
    (assets / 'index.html').write_text('PUBLIC-SYNTHETIC-SETUP-HTML')
    (assets / 'setup.js').write_text('PUBLIC-SYNTHETIC-SETUP-JS')
    (assets / 'google-login.dpapi').write_bytes(b'PRIVATE-SYNTHETIC-ENCRYPTED-SETTINGS')
    archive = tmp_path / 'source.zip'
    build(root, archive)
    with zipfile.ZipFile(archive) as stored:
        assert 'deploy/cloud/login-setup/index.html' in stored.namelist()
        assert 'deploy/cloud/login-setup/setup.js' in stored.namelist()
        assert not any(name.endswith('.dpapi') for name in stored.namelist())
        for name in stored.namelist():
            assert b'PRIVATE-TEST-MARKER' not in stored.read(name)
        manifest = json.loads(stored.read('CLOUD-BUNDLE.json'))
        assert manifest['requires'] and not manifest['contains_credentials']
        for entry in manifest['files']:
            assert hashlib.sha256(stored.read(entry['path'])).hexdigest() == entry['sha256']


def test_ci_gets_pure_robot_helpers_without_sdk_or_saved_device_material(tmp_path):
    root = project(tmp_path)
    helpers = root/'ep_runtime'
    helpers.mkdir()
    (helpers/'__init__.py').write_text('')
    (helpers/'manual_warning.py').write_text('class ManualWarning: pass')
    for name in ('state.json', 'private.dpapi', 'sdk.whl', 'worker.exe', 'record.log'):
        (helpers/name).write_text('PRIVATE-DEVICE-MARKER')
    archive = tmp_path/'ci-source.zip'
    build(root, archive)
    with zipfile.ZipFile(archive) as stored:
        assert 'ep_runtime/manual_warning.py' in stored.namelist()
        assert {name for name in stored.namelist() if name.startswith('ep_runtime/')} == {
            'ep_runtime/__init__.py', 'ep_runtime/manual_warning.py'}
        assert all(b'PRIVATE-DEVICE-MARKER' not in stored.read(name) for name in stored.namelist())


def test_existing_bundle_is_never_overwritten(tmp_path):
    root = project(tmp_path)
    output = tmp_path / 'existing.zip'
    output.write_bytes(b'preserve-original')
    with pytest.raises(FileExistsError):
        build(root, output)
    assert output.read_bytes() == b'preserve-original'


def test_same_source_bundle_is_reproducible(tmp_path):
    root = project(tmp_path)
    first = build(root, tmp_path / 'one.zip')
    second = build(root, tmp_path / 'two.zip')
    assert first['sha256'] == second['sha256']


def test_obvious_credential_in_source_stops_before_creating_bundle(tmp_path):
    root = project(tmp_path)
    (root / 'edge_hub/accidental.py').write_text('key = "tvly-' + 'a' * 30 + '"')
    output = tmp_path / 'unsafe.zip'
    with pytest.raises(ValueError, match='requires review'):
        build(root, output)
    assert not output.exists()


def test_preflight_never_reports_blank_windows_source_as_deployed(tmp_path):
    root = project(tmp_path)
    result = report(root, tmp_path / 'absent-settings', tmp_path / 'absent-model',
                    system='Windows', python=('3', '12', '10'))
    assert not result['ready_for_host_acceptance'] and not result['publicly_deployed']
    assert not next(item for item in result['checks'] if item['id'] == 'verified_data_cutover')['passed']
    assert not (tmp_path / 'absent-settings').exists()
    assert not (root / '.runtime').exists()


def test_preflight_does_not_read_or_echo_credentials(tmp_path):
    root = project(tmp_path)
    settings = tmp_path / 'settings'
    settings.mkdir()
    (settings / 'cloudflare-gemma-key.dpapi').write_bytes(b'SECRET-DO-NOT-READ')
    result = report(root, settings, tmp_path / 'model', system='Linux', python=('3', '12', '10'))
    assert 'SECRET-DO-NOT-READ' not in json.dumps(result)
    assert not result['ready_for_host_acceptance']
