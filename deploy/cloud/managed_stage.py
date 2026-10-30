"""Explicit Render storage acceptance boot; never a production data cutover.

Only non-secret metadata files are regenerated on the ephemeral filesystem.
Authoritative stores, controls, reservations and deletion receipts stay remote.
No schema initialization, model/voice credentials, defaults or local DB fallback.
"""
import json
import os
import re
from pathlib import Path

from deploy.cloud.database_profile import DatabaseProfile, unique_object
from deploy.cloud.google_identity import GoogleIdentityVerifier
from deploy.cloud.http_app import validate_origin

ROOT = Path('/tmp/neighbour-cloud-stage')
VARIABLE = 'NEIGHBOUR_MANAGED_STAGE'


def provision(value, *, environment=None, root=ROOT):
    env = os.environ if environment is None else environment
    root = Path(root)
    if (not isinstance(value, str) or not 1 <= len(value.encode('utf-8')) <= 32768
            or not root.is_absolute() or root.is_symlink()
            or any(parent.is_symlink() for parent in root.parents)):
        raise ValueError('explicit_managed_stage_required')
    try:
        data = json.loads(value, object_pairs_hook=unique_object)
        fields = {'format', 'service_id', 'origin', 'google_client_id', 'accounts', 'database_profile'}
        if (not isinstance(data, dict) or set(data) != fields or data['format'] != 'neighbour-managed-stage-v1'
                or not isinstance(data['service_id'], str) or not re.fullmatch(r'srv-[a-z0-9]{16,40}', data['service_id'])
                or env.get('RENDER_SERVICE_ID') != data['service_id']
                or env.get('RENDER_EXTERNAL_URL') != data['origin']
                or env.get('NEIGHBOUR_CREDENTIAL_BACKEND') != 'managed-environment'
                or env.get('NEIGHBOUR_SETTINGS_ROOT') != str(root / 'settings')
                or env.get('NEIGHBOUR_CLOUD_CONFIG') != str(root / 'metadata/host.json')
                or any(env.get(name) for name in ('NEIGHBOUR_SECRET_CLOUDFLARE_GEMMA',
                    'NEIGHBOUR_SECRET_AZURE_SPEECH_F0', 'NEIGHBOUR_SECRET_TAVILY'))):
            raise ValueError('invalid_stage_binding')
        host = validate_origin(data['origin'])
        if not host.endswith('.onrender.com'):
            raise ValueError('render_stage_origin_required')
        GoogleIdentityVerifier(data['google_client_id'], data['accounts'])  # Validates; no network.
        if 'staff' not in data['accounts'].values():
            raise ValueError('explicit_staff_required')
        for directory in (root, root / 'runtime', root / 'settings', root / 'scratch', root / 'metadata'):
            if directory.is_symlink():
                raise ValueError('unexpected_stage_path')
            directory.mkdir(mode=0o700, exist_ok=True)
            if os.name == 'posix' and (directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077):
                raise ValueError('private_owned_stage_paths_required')
        profile = data['database_profile']
        if profile.get('format') != 'neighbour-cloud-storage-v2':
            raise ValueError('explicit_api_verified_profile_required')
        DatabaseProfile(profile, runtime_root=root / 'runtime', settings_root=root / 'settings')  # No DB opens.
        config = {'format': 'neighbour-cloud-host-v1', 'origin': data['origin'],
            'google_client_id': data['google_client_id'], 'accounts': data['accounts'],
            'database_profile': str(root / 'metadata/databases.json'),
            'runtime_root': str(root / 'runtime'), 'settings_root': str(root / 'settings'),
            'scratch_root': str(root / 'scratch')}
        for path, content in ((root / 'metadata/databases.json', profile), (root / 'metadata/host.json', config)):
            encoded = json.dumps(content, sort_keys=True, separators=(',', ':')).encode('utf-8')
            if path.is_symlink():
                raise ValueError('unexpected_stage_file')
            if path.exists():
                if not path.is_file() or path.stat().st_size > 65536 or path.read_bytes() != encoded:
                    raise ValueError('existing_stage_metadata_requires_review')
            else:
                with path.open('xb') as handle:
                    handle.write(encoded)
                if os.name == 'posix':
                    path.chmod(0o600)
        return root / 'metadata/host.json'
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ValueError('managed_stage_configuration_required') from None
