"""Read-only deployment fingerprint checks, separate from hardware acceptance."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PureWindowsPath

from edge_hub.event_request import check_event_json_depth


def _unique_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('ambiguous deployment evidence')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('nonstandard deployment evidence')


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite deployment evidence')
    return number


def read_evidence_object(raw: bytes, *, max_bytes: int):
    if len(raw) > max_bytes:
        raise ValueError('deployment evidence too large')
    check_event_json_depth(raw, max_depth=32)
    value = json.loads(raw, object_pairs_hook=_unique_members,
                       parse_constant=_reject_constant, parse_float=_finite_float)
    if not isinstance(value, dict):
        raise TypeError('deployment evidence must be an object')
    return value


def file_sha256(path: Path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(root: Path):
    path = root / '.runtime/deployment-manifest.json'
    with path.open('rb') as source:
        raw = source.read(2_000_001)
    manifest = read_evidence_object(raw, max_bytes=2_000_000)
    if (manifest.get('schema_version') != 1 or not isinstance(manifest.get('build_id'), str)
            or not isinstance(manifest.get('files'), dict) or not manifest['files']
            or len(manifest['files']) > 5000):
        raise ValueError('invalid manifest')
    for name, digest in manifest['files'].items():
        relative = Path(name)
        forbidden = {'.runtime', '.vendor', '.venv', '.venv-audio', '.git', '.env', 'node_modules'}
        if (relative.is_absolute() or PureWindowsPath(name).drive or '\\' in name
                or '..' in relative.parts or any(part in forbidden for part in relative.parts)
                or not relative.parts or not (root / relative).resolve().is_relative_to(root.resolve())
                or not isinstance(digest, str) or len(digest) != 64
                or any(char not in '0123456789abcdef' for char in digest)):
            raise ValueError('invalid inventory entry')
    return manifest


def verify_files(root: Path):
    try:
        manifest = read_manifest(root)
    except FileNotFoundError:
        return {'status': 'manifest_missing', 'disk_matches_manifest': False}
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return {'status': 'invalid_manifest', 'disk_matches_manifest': False}
    return _verify_inventory(root, manifest)


def _verify_inventory(root: Path, manifest):
    # Reuse the same parsed inventory during startup; never verify a second
    # manifest and attach its result to an identity from the first one.
    changed, missing = [], []
    source_missing = manifest.get('missing_source_files', [])
    if not isinstance(source_missing, list) or any(not isinstance(item, str) for item in source_missing):
        return {'status': 'invalid_manifest', 'disk_matches_manifest': False}
    for name, expected in manifest['files'].items():
        try:
            actual = file_sha256(root / name)
        except OSError:
            missing.append(name)
            continue
        if actual != expected:
            changed.append(name)
    return {'status': 'verified' if not changed and not missing and not source_missing else 'files_differ',
            'build_id': manifest['build_id'], 'source_commit': manifest.get('source_commit'),
            'file_count': len(manifest['files']), 'changed': sorted(changed),
            'missing': sorted(missing), 'source_missing_count': len(source_missing),
            'disk_matches_manifest': not changed and not missing and not source_missing}


def loaded_identity(root: Path):
    # Called once at module import, NOT on each /health request after a file sync.
    result = {'build_id': None, 'source_commit': None, 'app_sha256': None}
    try:
        digest = file_sha256(root / 'edge_hub/app.py')
        result['app_sha256'] = digest
        manifest = read_manifest(root)
        if (manifest['files'].get('edge_hub/app.py') == digest
                and _verify_inventory(root, manifest)['disk_matches_manifest']):
            result.update(build_id=manifest['build_id'], source_commit=manifest.get('source_commit'))
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        pass
    return result
