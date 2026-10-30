"""Explicit formal managed boot, separate from the synthetic stage envelope.

Metadata attestations are not a replacement for the operator's real cutover
receipts. No defaults, schema creation, imports, billing calls or hardware.
Runtime-only files are references/metadata; all authoritative stores stay SQL.
"""
import json
import os
import re
from pathlib import Path

from deploy.cloud.database_profile import DatabaseProfile, endpoint, unique_object
from deploy.cloud.google_identity import GoogleIdentityVerifier
from deploy.cloud.http_app import validate_origin
from deploy.cloud.transcription_api import MODEL as WHISPER
from edge_hub.cloud_host_credentials import VARIABLES, reference

ROOT = Path('/tmp/neighbour-cloud-live')
VARIABLE = 'NEIGHBOUR_MANAGED_RELEASE'
SECRET_NAMES = {'cloudflare-gemma-key', 'azure-speech-f0-key', 'tavily-key',
                'turso-data-token', 'turso-read-token', 'retention-ledger-key'}


def provision(value, *, environment=None, root=ROOT):
    env = os.environ if environment is None else environment
    root = Path(root)
    try:
        if (not isinstance(value, str) or not 1 <= len(value.encode()) <= 65536
                or not root.is_absolute() or any(path.is_symlink() for path in (root, *root.parents))
                or any(name in env for name in ('NEIGHBOUR_STAGE_ENVELOPE', 'NEIGHBOUR_MANAGED_STAGE'))):
            raise ValueError('invalid_release_binding')
        data = json.loads(value, object_pairs_hook=unique_object)
        fields = {'format', 'service_id', 'origin', 'google_client_id', 'accounts',
                  'database_profile', 'backup_url', 'release_receipt', 'provider_profiles'}
        if (not isinstance(data, dict) or set(data) != fields or data['format'] != 'neighbour-managed-release-v1'
                or not re.fullmatch(r'srv-[a-z0-9]{16,40}', data['service_id'])
                or env.get('RENDER_SERVICE_ID') != data['service_id'] or env.get('RENDER_EXTERNAL_URL') != data['origin']
                or env.get('NEIGHBOUR_CREDENTIAL_BACKEND') != 'managed-environment'
                or env.get('NEIGHBOUR_SETTINGS_ROOT') != str(root / 'settings')
                or env.get('NEIGHBOUR_CLOUD_CONFIG') != str(root / 'metadata/host.json')):
            raise ValueError('invalid_release_binding')
        if not validate_origin(data['origin']).endswith('.onrender.com'):
            raise ValueError('owned_render_origin_required')
        GoogleIdentityVerifier(data['google_client_id'], data['accounts'])
        if 'staff' not in data['accounts'].values():
            raise ValueError('explicit_staff_required')
        proof = data['release_receipt']
        if (not isinstance(proof, dict) or set(proof) != {'format', 'native_writers_fenced', 'native_launch_fenced',
                'consistent_export_verified', 'exact_import_verified', 'restoration_verified',
                'single_formal_writer', 'source_manifest_sha256', 'initial_backup_id'}
                or proof['format'] != 'neighbour-cutover-v1'
                or any(proof[key] is not True for key in ('native_writers_fenced', 'native_launch_fenced',
                    'consistent_export_verified', 'exact_import_verified', 'restoration_verified', 'single_formal_writer'))
                or not re.fullmatch('[a-f0-9]{64}', proof['source_manifest_sha256'])
                or not re.fullmatch('[a-f0-9]{32}', proof['initial_backup_id'])):
            raise ValueError('completed_cutover_and_restore_receipt_required')
        profile = data['database_profile']
        if profile.get('format') != 'neighbour-cloud-storage-v2':
            raise ValueError('verified_free_profile_required')
        backup_url = endpoint(data['backup_url'])
        if (backup_url in {entry['url'] for entry in profile['databases'].values()}
                or any('-stage-' in endpoint(entry['url']) for entry in profile['databases'].values())
                or '-stage-' in backup_url):
            raise ValueError('independent_formal_stores_required')
        profiles = data['provider_profiles']
        if not isinstance(profiles, dict) or set(profiles) != {'cloudflare-gemma-free.json', 'azure-speech-f0.json', 'cloudflare-whisper-free.json'}:
            raise ValueError('explicit_free_provider_profiles_required')
        cf = profiles['cloudflare-gemma-free.json']
        az = profiles['azure-speech-f0.json']
        if (set(cf) != {'enabled', 'plan', 'ui_verified', 'account_id'} or cf['enabled'] is not True
                or cf['plan'] != 'Free' or cf['ui_verified'] is not True or not re.fullmatch('[a-f0-9]{32}', cf['account_id'])
                or az != {'sku': 'F0', 'region': 'eastasia'}
                or profiles['cloudflare-whisper-free.json'] != {'enabled': True, 'user_approved': True, 'model': WHISPER, 'plan': 'Free'}):
            raise ValueError('fixed_free_gemma_hiumaan_and_approved_whisper_required')
        for name in SECRET_NAMES:
            secret = env.get(VARIABLES[name])
            if (not isinstance(secret, str) or not 16 <= len(secret) <= 4096 or not secret.isascii()
                    or any(ord(char) <= 32 or ord(char) == 127 for char in secret)):
                raise ValueError('managed_release_credential_required')
        # Validate before creating any file. Existing paths must be owned and
        # private; references are immutable and never converted from DPAPI here.
        for path in (root, root / 'runtime', root / 'settings', root / 'scratch', root / 'metadata'):
            if path.is_symlink():
                raise ValueError('unexpected_release_path')
            path.mkdir(mode=0o700, exist_ok=True)
            if os.name == 'posix' and (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077):
                raise ValueError('private_release_paths_required')
        DatabaseProfile(profile, runtime_root=root / 'runtime', settings_root=root / 'settings')
        host = {'format': 'neighbour-cloud-host-v1', 'origin': data['origin'],
                'google_client_id': data['google_client_id'], 'accounts': data['accounts'],
                'database_profile': str(root / 'metadata/databases.json'),
                'runtime_root': str(root / 'runtime'), 'settings_root': str(root / 'settings'),
                'scratch_root': str(root / 'scratch')}
        contents = {root / 'metadata/databases.json': json.dumps(profile, sort_keys=True).encode(),
                    root / 'metadata/host.json': json.dumps(host, sort_keys=True).encode(),
                    root / 'metadata/release-receipt.json': json.dumps(proof, sort_keys=True).encode()}
        for name, content in profiles.items():
            contents[root / 'settings' / name] = json.dumps(content, sort_keys=True).encode()
        for name in SECRET_NAMES:
            contents[root / 'settings' / (name + '.dpapi')] = reference(name, mode='managed-environment')
        for path, content in contents.items():
            if path.is_symlink():
                raise ValueError('unexpected_release_file')
            if path.exists():
                if not path.is_file() or path.stat().st_size > 65536 or path.read_bytes() != content:
                    raise ValueError('existing_release_metadata_requires_review')
            else:
                with path.open('xb') as handle:
                    handle.write(content)
                if os.name == 'posix':
                    path.chmod(0o600)
        return {'config_path': root / 'metadata/host.json', 'backup_url': backup_url,
                'initial_backup_id': proof['initial_backup_id'], 'probe_id': proof['source_manifest_sha256']}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('managed_release_configuration_required') from None
