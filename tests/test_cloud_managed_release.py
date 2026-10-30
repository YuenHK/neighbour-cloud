import copy
import json
from datetime import UTC, datetime

import pytest

from deploy.cloud.database_profile import ROLE_FILES
from deploy.cloud.managed_release import SECRET_NAMES, provision
from deploy.cloud.transcription_api import MODEL
from edge_hub.cloud_host_credentials import VARIABLES, reference


@pytest.fixture
def release(tmp_path):
    root = tmp_path / 'explicit-live'
    metadata = {'format': 'neighbour-managed-release-v1', 'service_id': 'srv-' + 'a' * 24,
        'origin': 'https://neighbour.example.onrender.com',
        'google_client_id': '123-public.apps.googleusercontent.com', 'accounts': {'public-staff': 'staff'},
        'database_profile': {'format': 'neighbour-cloud-storage-v2', 'provider': 'turso-libsql',
            'plan': 'Free', 'mode': 'remote-primary', 'plan_verification': {'source': 'turso-platform-api',
                'organization': 'yuenhk', 'plan_id': 'starter', 'monthly_price': '0', 'overages': False,
                'checked_utc': datetime.now(UTC).isoformat(), 'receipt_sha256': 'a' * 64},
            'databases': {role: {'url': f'libsql://neighbour-live-{role.replace("_", "-")}.turso.io',
                'credential': 'turso-data-token', 'read_credential': 'turso-read-token'} for role in ROLE_FILES}},
        'backup_url': 'libsql://neighbour-live-backups.turso.io',
        'release_receipt': {'format': 'neighbour-cutover-v1', 'native_writers_fenced': True,
            'native_launch_fenced': True, 'consistent_export_verified': True, 'exact_import_verified': True,
            'restoration_verified': True, 'single_formal_writer': True, 'source_manifest_sha256': 'b' * 64,
            'initial_backup_id': 'c' * 32},
        'provider_profiles': {'cloudflare-gemma-free.json': {'enabled': True, 'plan': 'Free',
            'ui_verified': True, 'account_id': 'd' * 32}, 'azure-speech-f0.json': {'sku': 'F0', 'region': 'eastasia'},
            'cloudflare-whisper-free.json': {'enabled': True, 'user_approved': True, 'model': MODEL, 'plan': 'Free'}}}
    env = {'RENDER_SERVICE_ID': metadata['service_id'], 'RENDER_EXTERNAL_URL': metadata['origin'],
        'NEIGHBOUR_CREDENTIAL_BACKEND': 'managed-environment', 'NEIGHBOUR_SETTINGS_ROOT': str(root / 'settings'),
        'NEIGHBOUR_CLOUD_CONFIG': str(root / 'metadata/host.json')}
    env.update({VARIABLES[name]: 'PUBLIC-SYNTHETIC-' + 'x' * 40 for name in SECRET_NAMES})
    return root, metadata, env


def test_only_reference_files_and_approved_free_profiles_are_created_not_databases_or_raw_keys(release):
    root, metadata, env = release
    result = provision(json.dumps(metadata), environment=env, root=root)
    assert result['backup_url'] == metadata['backup_url'] and result['initial_backup_id'] == 'c' * 32
    assert result['config_path'].is_file()
    assert not list(root.rglob('*.sqlite3'))
    for name in SECRET_NAMES:
        value = (root / 'settings' / (name + '.dpapi')).read_bytes()
        assert value == reference(name, mode='managed-environment')
        assert env[VARIABLES[name]].encode() not in value
    first = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    assert provision(json.dumps(metadata), environment=env, root=root) == result
    assert first == {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}


@pytest.mark.parametrize('field', ['native_writers_fenced', 'native_launch_fenced', 'consistent_export_verified',
                                  'exact_import_verified', 'restoration_verified', 'single_formal_writer'])
def test_every_formal_cutover_attestation_is_required_and_no_paths_created_on_failure(release, field):
    root, metadata, env = release
    metadata['release_receipt'][field] = False
    with pytest.raises(ValueError, match='managed_release_configuration_required'):
        provision(json.dumps(metadata), environment=env, root=root)
    assert not root.exists()


@pytest.mark.parametrize('change', ['stage_envelope', 'empty_stage', 'old_stage', 'sku', 'whisper',
                                   'missing_secret', 'backup_same_as_live', 'stage_database', 'paid_plan'])
def test_stage_paid_unapproved_or_incomplete_configuration_never_opens_formal(release, change):
    root, metadata, env = release
    if change in ('stage_envelope', 'empty_stage', 'old_stage'):
        env['NEIGHBOUR_MANAGED_STAGE' if change == 'old_stage' else 'NEIGHBOUR_STAGE_ENVELOPE'] = '' if change == 'empty_stage' else '{}'
    elif change == 'sku':
        metadata['provider_profiles']['azure-speech-f0.json']['sku'] = 'S0'
    elif change == 'whisper':
        metadata['provider_profiles']['cloudflare-whisper-free.json']['user_approved'] = False
    elif change == 'missing_secret':
        env.pop(VARIABLES['azure-speech-f0-key'])
    elif change == 'backup_same_as_live':
        metadata['backup_url'] = metadata['database_profile']['databases']['cases']['url']
    elif change == 'stage_database':
        metadata['database_profile']['databases']['cases']['url'] = 'libsql://neighbour-stage-cases.turso.io'
    else:
        metadata['database_profile']['plan_verification']['overages'] = True
    with pytest.raises(ValueError, match='managed_release_configuration_required'):
        provision(json.dumps(metadata), environment=env, root=root)


def test_existing_metadata_is_not_overwritten_when_provider_or_identity_changes(release):
    root, metadata, env = release
    result = provision(json.dumps(metadata), environment=env, root=root)
    original = result['config_path'].read_bytes()
    changed = copy.deepcopy(metadata)
    changed['accounts']['another-account'] = 'staff'
    with pytest.raises(ValueError, match='managed_release_configuration_required'):
        provision(json.dumps(changed), environment=env, root=root)
    assert result['config_path'].read_bytes() == original
