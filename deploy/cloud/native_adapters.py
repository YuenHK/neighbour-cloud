"""Prepare NEW cloud adapter files from a verified private native export.

This is not an upload/cutover. Native blurred historical images are archived
with exact paths, hashes and event bindings, not relabelled as new EP three-view
or cloud-AI reviewed photos. Missing original files get explicit records.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from deploy.cloud.deletion_ledger import DeletionLedger
from deploy.cloud.native_export import DATABASES, NativeExportError, file_identity, safe_directory
from deploy.cloud.photo_store import PhotoStore, validate_image
from deploy.cloud.state_store import StateStore

LEGACY_TABLES = {'native_evidence_blobs', 'native_evidence_bindings', 'native_evidence_missing'}


def prepare(export_root, data_root, output, *, signing_key):
    export, data = safe_directory(export_root), safe_directory(data_root)
    marker = export / 'NATIVE-EXPORT.json'
    file_identity(marker, required=True, maximum=65536)
    receipt = json.loads(marker.read_text(encoding='utf-8'))
    if receipt.get('format') != 'neighbour-native-export-v1' or set(receipt.get('databases', {})) != set(DATABASES):
        raise NativeExportError('verified_native_export_required')
    identities = {}
    for role, filename in DATABASES.items():
        identities[role] = file_identity(export / filename, required=True)
        if any(identities[role].get(field) != receipt['databases'][role].get(field) for field in ('bytes', 'sha256')):
            raise NativeExportError('native_export_changed')
    if (receipt.get('original_cloud_ledger_exists') is not False
            or receipt.get('original_cloud_signing_key_exists') is not False):
        raise NativeExportError('existing_native_ledger_requires_exact_import')
    output = Path(output).absolute()
    if (any(item.is_symlink() for item in (output, *output.parents)) or output.exists()
            or not output.parent.is_dir() or output.is_relative_to(data)):
        raise NativeExportError('new_private_adapter_directory_required')
    output.mkdir()
    with (output / 'INCOMPLETE.json').open('x', encoding='utf-8') as handle:
        json.dump({'ready': False, 'cutover_ready': False}, handle)
    with closing(sqlite3.connect(output / 'cloud-control.sqlite3')) as db:
        controls = StateStore(db, initialize=True)
        controls.seed(receipt['controls'])
        for name, value in receipt['controls'].items():
            if controls.read(name) != value:
                raise NativeExportError('native_control_import_mismatch')
    with closing(sqlite3.connect(output / 'cloud-deletion-ledger.sqlite3')) as ledger_db:
        ledger = DeletionLedger(ledger_db, signing_key, initialize=True)
        with closing(sqlite3.connect((export / DATABASES['cases']).as_uri() + '?mode=ro&immutable=1', uri=True)) as cases:
            erased = cases.execute('SELECT x.id,x.erased_at_ms,COALESCE(c.revision,1) FROM case_privacy_expiry x '
                                   'LEFT JOIN service_cases c ON c.id=x.id').fetchall()
        records = [{'kind': 'case', 'target': row[0], 'revision': row[2], 'erased_ms': row[1]} for row in erased]
        with closing(sqlite3.connect((export / DATABASES['events']).as_uri() + '?mode=ro&immutable=1', uri=True)) as events:
            events.row_factory = sqlite3.Row
            rows = events.execute('SELECT * FROM events ORDER BY id').fetchall()
            for row in rows:
                details = json.loads(row['details_json'])
                if details.get('retention_erased') is True:
                    records.append({'kind': 'event', 'target': row['id'], 'revision': 1,
                                    'erased_ms': details['erased_at_ms']})
        for offset in range(0, len(records), 500):
            ledger.append(records[offset:offset + 500])
        checkpoint = ledger.checkpoint()
    copied, missing, bindings, total = {}, {}, 0, 0
    with closing(sqlite3.connect(output / 'cloud-photos.sqlite3')) as db:
        PhotoStore(db)
        with db:
            db.execute('CREATE TABLE native_evidence_blobs(key TEXT PRIMARY KEY,digest TEXT NOT NULL,content BLOB NOT NULL)')
            db.execute('CREATE TABLE native_evidence_bindings(event_id TEXT NOT NULL,key TEXT NOT NULL,'
                       'PRIMARY KEY(event_id,key))')
            db.execute('CREATE TABLE native_evidence_missing(event_id TEXT NOT NULL,key TEXT NOT NULL,'
                       'PRIMARY KEY(event_id,key))')
            for row in rows:
                details, key = json.loads(row['details_json']), row['evidence']
                if not key:
                    continue
                if (details.get('source') == 'ep_patrol_local' or details.get('photos')
                        or details.get('retention_erased') is True):
                    raise NativeExportError('native_three_photo_or_erased_bundle_requires_exact_import')
                if (not isinstance(key, str) or len(key) > 240
                        or not re.fullmatch(r'events/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+-blurred\.(?:jpg|jpeg|png)', key)):
                    raise NativeExportError('unrecognised_native_evidence_path')
                source = data / key
                info = file_identity(source, maximum=1_500_000)
                if not info['exists']:
                    db.execute('INSERT INTO native_evidence_missing VALUES(?,?)', (row['id'], key))
                    missing[row['id']] = key
                    continue
                if key not in copied:
                    image = source.read_bytes()
                    if hashlib.sha256(image).hexdigest() != info['sha256']:
                        raise NativeExportError('native_evidence_changed')
                    validate_image(image, 'PNG' if key.endswith('.png') else 'JPEG')
                    total += len(image)
                    if total > 128 * 1024 * 1024:
                        raise NativeExportError('native_evidence_budget_exceeded')
                    db.execute('INSERT INTO native_evidence_blobs VALUES(?,?,?)', (key, info['sha256'], image))
                    copied[key] = info
                elif info != copied[key]:
                    raise NativeExportError('native_evidence_changed')
                db.execute('INSERT INTO native_evidence_bindings VALUES(?,?)', (row['id'], key))
                bindings += 1
    if (any(file_identity(data / key) != info for key, info in copied.items())
            or any((data / key).exists() for key in missing.values())
            or any(file_identity(export / DATABASES[role]) != identity for role, identity in identities.items())):
        raise NativeExportError('native_adapter_source_changed')
    result = {'format': 'neighbour-native-adapters-v1', 'phase': receipt['phase'],
              'cross_database_consistent': receipt['cross_database_consistent'], 'cutover_ready': False,
              'first_cloud_ledger_created': True, 'native_erasure_intents_preserved': len(records),
              'ledger_checkpoint': checkpoint, 'controls_imported': len(receipt['controls']),
              'legacy_image_count': len(copied), 'legacy_image_bindings': bindings,
              'legacy_missing_bindings': len(missing), 'legacy_image_bytes': total,
              'legacy_evidence_manifest': copied, 'missing_original_evidence': missing,
              'three_view_EP_photos': 0, 'cloud_AI_reviewed': False,
              'private_data_uploaded': False, 'signing_key_saved_in_this_directory': False,
              'databases': {name: file_identity(output / name, required=True) for name in
                            ('cloud-control.sqlite3', 'cloud-deletion-ledger.sqlite3', 'cloud-photos.sqlite3')}}
    with (output / 'NATIVE-ADAPTERS.json').open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    return result
