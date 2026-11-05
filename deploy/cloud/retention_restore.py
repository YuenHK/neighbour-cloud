"""Recover into a NEW private file, reconciling an independent live ledger.

Never selects an old checkpoint from the backup itself. No input backup or
running database is changed. Only return ready after ledger, data, FK and final
file checks; incomplete outputs must never be served or started by the caller.
"""
import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from deploy.cloud.closed_backup import unchanged_closed_backup
from deploy.cloud.sql_snapshot import snapshot

PRIVATE_CASE_FIELDS = {'location', 'message', 'contact', 'assignee', 'note', 'profile', 'unit'}


def columns(db, table):
    # All callers below use fixed internal table names, never request strings.
    return {row[1] for row in db.execute(f'PRAGMA table_info({table})')}


def require_schema(db, scope):
    if scope == 'estate':
        actual = columns(db, 'cloud_operations')
        if actual and not {'namespace', 'identity', 'payload'} <= actual:
            raise ValueError('unrecognised_retention_restore_schema')
        return  # Older estate backups may predate the optional extension table.
    tables = {'cases': ('service_cases', {'id', 'status', 'message', 'location', 'contact'}),
              'events': ('events', {'id', 'zone', 'evidence', 'details_json'}),
              'photos': ('cloud_photos', {'key', 'event_id', 'content', 'digest'})}
    if scope not in tables:
        raise ValueError('unknown_retention_restore_scope')
    table, expected = tables[scope]
    if not expected <= columns(db, table):
        raise ValueError('unrecognised_retention_restore_schema')
    if scope == 'photos' and not {'key', 'event_id', 'erased_ms'} <= columns(db, 'cloud_photo_tombstones'):
        raise ValueError('unrecognised_retention_restore_schema')


def purge_records(db, scope, records):
    """Bounded operator purge; no N+1 remote PRAGMAs or photo round trips."""
    kind = 'case_purge' if scope in ('cases', 'estate') else 'event_purge'
    selected = [r for r in records if r['kind'] == kind]
    changed = 0
    if not selected:
        return changed
    if scope == 'estate' and not columns(db, 'cloud_operations'):
        return changed  # Early backups predate optional case-photo ciphertext.
    children = [(table, field) for table, field in [('service_case_activity','case_id'), ('patrol_case_links','case_id'),
        ('resident_session_cases','case_id'), ('resident_session_turns','case_id'), ('resident_support_links','case_id')]
        if scope == 'cases' and field in columns(db, table)]
    legacy = scope == 'photos' and bool(columns(db, 'native_evidence_bindings'))
    completion = scope == 'events' and bool(columns(db, 'event_completion'))
    photo_retention = scope == 'photos' and bool(columns(db, 'cloud_photo_retention'))
    if scope == 'cases':
        db.execute('CREATE TABLE IF NOT EXISTS case_privacy_expiry(id TEXT PRIMARY KEY,erased_at_ms INTEGER NOT NULL)')
    if scope == 'photos':
        db.execute('CREATE TABLE IF NOT EXISTS cloud_erased_events(event_id TEXT PRIMARY KEY,erased_ms INTEGER NOT NULL)')
    for start in range(0, len(selected), 200):
        batch = selected[start:start+200]
        targets = [r['target'] for r in batch]
        marks = ','.join('?' for _ in batch)
        pairs = ','.join('(?,?)' for _ in batch)
        values = tuple(value for r in batch for value in (r['target'], r['erased_ms']))
        if scope == 'cases':
            for table, field in children:
                db.execute(f'DELETE FROM {table} WHERE {field} IN ({marks})', targets)
            changed += db.execute(f'DELETE FROM service_cases WHERE id IN ({marks})', targets).rowcount
            db.execute('INSERT OR IGNORE INTO case_privacy_expiry VALUES ' + pairs, values)
        elif scope == 'events':
            if completion:
                db.execute(f'DELETE FROM event_completion WHERE event_id IN ({marks})', targets)
            changed += db.execute(f'DELETE FROM events WHERE id IN ({marks})', targets).rowcount
        elif scope == 'estate':
            changed += db.execute(f'DELETE FROM cloud_operations WHERE namespace=? AND identity IN ({marks})',
                                  ('resident-case-photo-v1', *targets)).rowcount
        else:
            db.execute('WITH purges(event_id,erased_ms) AS (VALUES ' + pairs + ') '
                'INSERT OR IGNORE INTO cloud_photo_tombstones '
                'SELECT p.key,p.event_id,r.erased_ms FROM cloud_photos p JOIN purges r ON r.event_id=p.event_id', values)
            db.execute('INSERT OR IGNORE INTO cloud_erased_events VALUES ' + pairs, values)
            changed += db.execute(f'DELETE FROM cloud_photos WHERE event_id IN ({marks})', targets).rowcount
            if photo_retention:
                db.execute(f'DELETE FROM cloud_photo_retention WHERE event_id IN ({marks})', targets)
            if legacy:
                changed += db.execute(f'DELETE FROM native_evidence_bindings WHERE event_id IN ({marks})', targets).rowcount
                db.execute(f'DELETE FROM native_evidence_missing WHERE event_id IN ({marks})', targets)
    if legacy:
        db.execute('DELETE FROM native_evidence_blobs WHERE NOT EXISTS '
                   '(SELECT 1 FROM native_evidence_bindings b WHERE b.key=native_evidence_blobs.key)')
    return changed


def reconcile(db, scope, records):
    require_schema(db, scope)
    changed = purge_records(db, scope, records)
    records = [r for r in records if r['kind'] not in ('case_purge', 'event_purge')]
    if scope == 'estate':
        if columns(db, 'cloud_operations'):
            for record in records:
                if record['kind'] == 'case':
                    changed += db.execute('DELETE FROM cloud_operations WHERE namespace=? AND identity=?',
                                          ('resident-case-photo-v1', record['target'])).rowcount
        return changed
    if scope == 'cases':
        fields = sorted(PRIVATE_CASE_FIELDS & columns(db, 'service_cases'))
        activity = columns(db, 'service_case_activity')
        db.execute('CREATE TABLE IF NOT EXISTS case_privacy_expiry(id TEXT PRIMARY KEY,erased_at_ms INTEGER NOT NULL)')
        for record in records:
            if record['kind'] != 'case':
                continue
            target, stamp = record['target'], record['erased_ms']
            changed += db.execute('UPDATE service_cases SET ' + ','.join(f'{field}=?' for field in fields) + ' WHERE id=?',
                                  (*('已按保存期限清除' if field == 'message' else '' for field in fields), target)).rowcount
            if 'case_id' in activity:
                for field in ('note', 'assignee'):
                    if field in activity:
                        db.execute(f"UPDATE service_case_activity SET {field}='' WHERE case_id=?", (target,))
            db.execute('INSERT OR IGNORE INTO case_privacy_expiry VALUES(?,?)', (target, stamp))
    elif scope == 'events':
        for record in records:
            if record['kind'] == 'event':
                changed += db.execute('UPDATE events SET zone=?,evidence=NULL,details_json=? WHERE id=?',
                                      ('已按保存期限清除', json.dumps({'retention_erased': True,
                                       'erased_at_ms': record['erased_ms']}), record['target'])).rowcount
    else:
        db.execute('CREATE TABLE IF NOT EXISTS cloud_erased_events(event_id TEXT PRIMARY KEY,erased_ms INTEGER NOT NULL)')
        legacy = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE name IN "
                  "('native_evidence_blobs','native_evidence_bindings','native_evidence_missing')")}
        if legacy and len(legacy) != 3:
            raise ValueError('unrecognised_native_evidence_archive_schema')
        for record in records:
            if record['kind'] != 'event':
                continue
            target, stamp = record['target'], record['erased_ms']
            keys = db.execute('SELECT key FROM cloud_photos WHERE event_id=?', (target,)).fetchall()
            for row in keys:
                db.execute('INSERT OR IGNORE INTO cloud_photo_tombstones VALUES(?,?,?)', (row[0], target, stamp))
            db.execute('INSERT OR IGNORE INTO cloud_erased_events VALUES(?,?)', (target, stamp))
            changed += db.execute('DELETE FROM cloud_photos WHERE event_id=?', (target,)).rowcount
            if legacy:
                # A legacy file may be shared by several old events. Remove
                # its expired binding; erase bytes only after the last one.
                changed += db.execute('DELETE FROM native_evidence_bindings WHERE event_id=?', (target,)).rowcount
                db.execute('DELETE FROM native_evidence_missing WHERE event_id=?', (target,))
        if legacy:
            db.execute('DELETE FROM native_evidence_blobs WHERE NOT EXISTS '
                       '(SELECT 1 FROM native_evidence_bindings b WHERE b.key=native_evidence_blobs.key)')
    return changed


def recover(backup, destination, *, expected_sha256, ledger, live_checkpoint, scope, timeout=30):
    if type(timeout) not in (int, float) or not 0 < timeout <= 120:
        raise ValueError('bounded_retention_restore_timeout_required')
    deadline = time.monotonic() + timeout

    def check():
        if time.monotonic() > deadline:
            raise ValueError('retention_restore_deadline')

    backup, destination = Path(backup).absolute(), Path(destination).absolute()
    if (not isinstance(expected_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_sha256)
            or not backup.is_file() or any(path.is_symlink() for path in (backup, *backup.parents))
            or backup.stat().st_size > 128 * 1024 * 1024
            or any(Path(str(backup) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))):
        raise ValueError('closed_verified_backup_required')
    if hashlib.sha256(backup.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('retention_restore_backup_hash_mismatch')
    records = ledger.records(live_checkpoint)  # Fails before an output is created.
    check()
    with closing(sqlite3.connect(backup.as_uri() + '?mode=ro&immutable=1', uri=True)) as source:
        source.execute('PRAGMA trusted_schema=OFF')
        require_schema(source, scope)
        snapshot(source, destination, timeout=max(.001, deadline - time.monotonic()))
    # sqlite3's context manager commits; closing is explicit below.
    target = sqlite3.connect(destination)
    try:
        target.execute('PRAGMA trusted_schema=OFF')
        target.execute('PRAGMA secure_delete=ON')
        target.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        with target:
            target.execute('BEGIN IMMEDIATE')
            applied = reconcile(target, scope, records)
        target.execute('VACUUM')
        if target.execute('PRAGMA quick_check').fetchall() != [('ok',)] or target.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('retention_restore_integrity_failed')
        check()
    finally:
        target.close()
    if (ledger.checkpoint() != live_checkpoint
            or not unchanged_closed_backup(backup, expected_sha256)):
        raise ValueError('retention_restore_source_changed')
    final_digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    check()
    return {'ready': True, 'scope': scope, 'reconciled_records': applied,
            'ledger_sequence': live_checkpoint['seq'],
            'sha256': final_digest,
            'source_unchanged': True, 'destination_is_new': True}
