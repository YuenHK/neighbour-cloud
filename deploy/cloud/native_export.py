"""Private native snapshots for a reviewed cloud import, never a cutover.

Preview is safe while the native services run, but the six read transactions
are NOT a cross-database snapshot. A final export needs a live writer-fence
verifier before, during and after copying, plus unchanged DB/WAL and control
files. Nothing here stops a process, connects a robot, uploads or resets usage.
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from deploy.cloud.sql_snapshot import snapshot
from deploy.cloud.state_store import NAMES, validate

DATABASES = {'cases': 'service-desk.sqlite3', 'events': 'events.sqlite3',
             'estate': 'estate-information.sqlite3', 'memory': 'assistant-memory.sqlite3',
             'journal': 'staff-access.sqlite3', 'usage': 'cloud-usage.sqlite3'}
EPOCH = '1970-01-01T00:00:00+00:00'


class NativeExportError(ValueError):
    pass


def safe_directory(value):
    path = Path(value).absolute()
    if (not path.is_dir() or path == path.parent
            or any(item.is_symlink() for item in (path, *path.parents))):
        raise NativeExportError('native_directory_requires_review')
    return path.resolve()


def file_identity(path, *, required=False, maximum=128 * 1024 * 1024):
    path = Path(path)
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise NativeExportError('native_symlink_requires_review')
    if not path.exists():
        if required:
            raise NativeExportError('native_required_source_missing')
        return {'exists': False}
    before = path.stat()
    if not path.is_file() or before.st_size > maximum:
        raise NativeExportError('native_file_requires_review')
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise NativeExportError('native_source_changed_during_read')
    return {'exists': True, 'bytes': before.st_size, 'sha256': digest}


def controls(settings):
    """Absent native CF stop files mean inactive, not a new zero usage ledger.

    Azure's saved pause flag is required. Every absence is retained as source
    evidence and checked again; a newly arriving stop file invalidates a final
    export. Existing flags are never shortened, deleted or overwritten.
    """
    values, identities = {}, {}
    for name in sorted(NAMES):
        path = settings / name
        identities[name] = file_identity(path, required=name == 'azure-voice-control.json', maximum=16384)
        if identities[name]['exists']:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != identities[name]['sha256']:
                raise NativeExportError('native_controls_changed')
            value = json.loads(raw)
        else:
            value = {'until': EPOCH}
            if name.endswith('cooldown.json'):
                value['reason'] = 'network'
        values[name] = validate(name, value)
    return values, identities


def prepare(runtime_root, settings_root, output, *, phase='preview', writer_fence=None):
    runtime, settings = safe_directory(runtime_root), safe_directory(settings_root)
    output = Path(output).absolute()
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise NativeExportError('new_private_export_directory_required')
    output = output.resolve()
    if (runtime == settings or phase not in ('preview', 'fenced') or output.exists()
            or not output.parent.is_dir() or output.is_relative_to(runtime) or output.is_relative_to(settings)
            or any(path.is_symlink() for path in (output, *output.parents))):
        raise NativeExportError('new_private_export_directory_required')
    if phase == 'fenced' and not callable(writer_fence):
        raise NativeExportError('source_writer_fence_required')

    def fence():
        if phase == 'fenced' and writer_fence() is not True:
            raise NativeExportError('native_source_writers_not_fenced')

    fence()
    # These adapters do not currently exist in native installations. If they
    # appear, keep them and require a separate exact import, never reseed them.
    if any((settings / name).exists() for name in (
            'cloud-control.sqlite3', 'cloud-deletion-ledger.sqlite3', 'retention-ledger-key.dpapi')):
        raise NativeExportError('existing_native_cloud_adapters_require_exact_import')
    flags, flag_identity = controls(settings)
    sources = {role: (settings if role == 'usage' else runtime) / name for role, name in DATABASES.items()}

    def source_identities():
        return {role: {suffix or 'database': file_identity(Path(str(path) + suffix), required=not suffix)
                       for suffix in ('', '-wal', '-journal')} for role, path in sources.items()}

    before = source_identities()
    receipt_root = runtime / 'retention-receipts'

    def receipt_identities():
        if not receipt_root.exists():
            return {}
        safe_directory(receipt_root)
        files = sorted(receipt_root.glob('*.json'))
        if len(files) > 10000:
            raise NativeExportError('native_receipt_inventory_requires_review')
        return {path.name: file_identity(path, required=True, maximum=65536) for path in files}

    original_receipts = receipt_identities()
    output.mkdir()
    incomplete = output / 'INCOMPLETE.json'
    incomplete.write_text(json.dumps({'format': 'neighbour-native-export-v1', 'ready': False,
                                     'cutover_ready': False}), encoding='utf-8')
    copied = {}
    for role, source in sources.items():
        fence()
        target = output / DATABASES[role]
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            info = snapshot(db, target, timeout=60)
        copied[role] = {**file_identity(target, required=True), 'file': target.name, **info}
    with closing(sqlite3.connect((output / DATABASES['memory']).as_uri() + '?mode=ro', uri=True)) as memory:
        protected = memory.execute("SELECT COUNT(*) FROM memories WHERE text LIKE '%MB842%' OR id LIKE '%MB842%'").fetchone()[0]
        if protected < 1:
            raise NativeExportError('protected_memory_marker_not_found')
    receipts = {}
    original = receipt_root
    if original.exists():
        original = safe_directory(original)
        files = sorted(original.glob('*.json'))
        if len(files) > 10000:
            raise NativeExportError('native_receipt_inventory_requires_review')
        target = output / 'native-retention-receipts'
        target.mkdir()
        for path in files:
            info = file_identity(path, required=True, maximum=65536)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != info['sha256']:
                raise NativeExportError('native_receipt_changed')
            with (target / path.name).open('xb') as handle:
                handle.write(raw)
            receipts[path.name] = info
    fence()
    after_flags, after_flag_identity = controls(settings)
    after = source_identities()
    stable = (before == after and flags == after_flags and flag_identity == after_flag_identity
              and original_receipts == receipts == receipt_identities()
              and not any((settings / name).exists() for name in (
                  'cloud-control.sqlite3', 'cloud-deletion-ledger.sqlite3', 'retention-ledger-key.dpapi')))
    if phase == 'fenced' and not stable:
        raise NativeExportError('fenced_native_sources_changed')
    audit = runtime / 'robot-control.sqlite3'
    result = {'format': 'neighbour-native-export-v1', 'created_utc': datetime.now(UTC).isoformat(),
              'phase': phase, 'source_fence_verified': phase == 'fenced', 'source_files_stable': stable,
              'cross_database_consistent': phase == 'fenced' and stable, 'cutover_ready': False,
              'databases': copied, 'controls': flags, 'control_sources': flag_identity,
              'native_retention_receipts': receipts, 'protected_memory_marker_matches': protected,
              'original_cloud_ledger_exists': False, 'original_cloud_signing_key_exists': False,
              'robot_safety_audit_retained_at_source': file_identity(audit),
              'photos_migrated': False, 'private_data_uploaded': False,
              'next': 'photo binding, exact remote import, current ledger, quota/control preservation, durable restore and one writer'}
    with (output / 'NATIVE-EXPORT.json').open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    # Keep the first marker as evidence: consumers accept only NATIVE-EXPORT,
    # never the presence of a directory or an incomplete snapshot file.
    return result
