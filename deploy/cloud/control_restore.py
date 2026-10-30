"""Offline NEW-copy preparation: a backup must not weaken known protections.

No service starts, unpause, quota reset, automatic recovery or writer fencing.
The live control store must still be an independently trusted authority.
"""
import hashlib
import json
import math
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from deploy.cloud.closed_backup import unchanged_closed_backup
from deploy.cloud.runtime_storage import RuntimeStorage
from deploy.cloud.sql_snapshot import snapshot
from deploy.cloud.state_store import NAMES, StateStore

VOICE = 'azure-voice-control.json'
COOLDOWN = 'cloudflare-gemma-cooldown.json'


class ControlRestoreError(ValueError):
    pass


def read_controls(db, check):
    if db.in_transaction:
        raise ControlRestoreError('control_restore_requires_dedicated_connection')
    with db:
        db.execute('BEGIN')
        schema = db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if ({row[1] for row in schema if row[0] == 'table'} != {'cloud_state'}
                or any(row[0] not in ('table', 'index') for row in schema)):
            raise ControlRestoreError('control_restore_schema_requires_review')
        columns = db.execute('PRAGMA table_info(cloud_state)').fetchall()
        if ([(row[1], row[2].upper(), row[3], row[5]) for row in columns] != [
                ('name', 'TEXT', 0, 1), ('payload', 'TEXT', 1, 0),
                ('revision', 'INTEGER', 1, 0), ('updated_ms', 'INTEGER', 1, 0)]):
            raise ControlRestoreError('control_restore_schema_requires_review')
        metadata = tuple(db.execute(f'PRAGMA {name}').fetchone()[0] for name in ('user_version', 'application_id'))
        if any(type(value) is not int or not -(2**31) <= value < 2**31 for value in metadata):
            raise ControlRestoreError('control_restore_schema_requires_review')
        rows = db.execute('SELECT name,revision,updated_ms,LENGTH(payload),TYPEOF(payload) '
                          'FROM cloud_state ORDER BY name LIMIT 4').fetchall()
        if len(rows) != 3 or {row[0] for row in rows} != NAMES:
            raise ControlRestoreError('control_restore_explicit_flags_required')
        store = StateStore(db)
        values = {}
        for name, revision, updated, length, kind in rows:
            check()
            if (type(revision) is not int or not 1 <= revision < 2**63
                    or type(updated) is not int or not 0 <= updated < 2**63
                    or kind != 'text' or type(length) is not int or not 0 < length <= 1024):
                raise ControlRestoreError('control_restore_flags_require_review')
            values[name] = (store.read(name), revision, updated)
    check()
    return values, metadata


def fingerprint(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def conservative(old, current):
    merged = {}
    stamp = int(time.time() * 1000)
    for name in sorted(NAMES):
        revision = max(old[name][1], current[name][1])
        if revision == 2**63 - 1:
            raise ControlRestoreError('control_restore_revision_requires_review')
        a, b = old[name][0], current[name][0]
        if name == VOICE:
            value = {'paused': a['paused'] or b['paused']}
        else:
            left, right = datetime.fromisoformat(a['until']), datetime.fromisoformat(b['until'])
            value = dict(a if left > right else b)
            if name == COOLDOWN and left == right:
                value['reason'] = 'rate_limit' if 'rate_limit' in (a['reason'], b['reason']) else 'network'
        merged[name] = (value, revision + 1,
                        max(stamp, old[name][2], current[name][2]))
    return merged


def recover_controls(backup, destination, *, expected_sha256, storage, timeout=30, clock=time.monotonic):
    if (not isinstance(storage, RuntimeStorage) or type(timeout) not in (int, float)
            or not math.isfinite(timeout) or not 0 < timeout <= 120 or not callable(clock)):
        raise ControlRestoreError('control_restore_configuration_required')
    deadline = clock() + timeout

    def check():
        if clock() >= deadline:
            raise ControlRestoreError('control_restore_deadline')

    def sha(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    def live_state():
        path = storage.settings_root / 'cloud-control.sqlite3'
        with closing(storage.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            return read_controls(db, check)

    try:
        backup, destination = Path(backup).absolute(), Path(destination).absolute()
        if (not isinstance(expected_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_sha256)
                or not backup.is_file() or backup.stat().st_size > 128 * 1024 * 1024
                or any(path.is_symlink() for path in (backup, *backup.parents, destination, *destination.parents))
                or destination.exists() or not destination.parent.is_dir()
                or any(Path(str(backup) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))
                or sha(backup) != expected_sha256):
            raise ControlRestoreError('closed_verified_control_backup_and_new_destination_required')
        current = live_state()
        with closing(sqlite3.connect(backup.as_uri() + '?mode=ro&immutable=1', uri=True)) as source:
            source.execute('PRAGMA trusted_schema=OFF')
            original = read_controls(source, check)
            if original[1] != current[1]:
                raise ControlRestoreError('control_restore_schema_version_requires_review')
            merged = conservative(original[0], current[0])
            check()
            snapshot(source, destination, timeout=max(.001, deadline-clock()), clock=clock)
        with closing(sqlite3.connect(destination)) as target:
            target.execute('PRAGMA trusted_schema=OFF')
            target.set_progress_handler(lambda: int(clock() >= deadline), 1000)
            if read_controls(target, check) != original:
                raise ControlRestoreError('control_restore_backup_changed')
            with target:
                target.execute('BEGIN IMMEDIATE')
                for name, (value, revision, updated) in merged.items():
                    target.execute('UPDATE cloud_state SET payload=?,revision=?,updated_ms=? WHERE name=?',
                        (json.dumps(value, sort_keys=True), revision, updated, name))
            if read_controls(target, check) != (merged, current[1]):
                raise ControlRestoreError('control_restore_merge_failed')
            if (target.execute('PRAGMA quick_check').fetchall() != [('ok',)]
                    or target.execute('PRAGMA foreign_key_check').fetchall()):
                raise ControlRestoreError('control_restore_integrity_failed')
        if live_state() != current:
            raise ControlRestoreError('control_restore_live_changed')
        if not unchanged_closed_backup(backup, expected_sha256):
            raise ControlRestoreError('control_restore_backup_changed')
        check()
        result = {'prepared': True, 'cutover_ready': False, 'production_replaced': False,
                  'automatic_unpause': False, 'requires_operator_review': True,
                  'live_fingerprint': fingerprint(current), 'sha256': sha(destination)}
        check()
        return result
    except ControlRestoreError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error):
        raise ControlRestoreError('control_restore_requires_review') from None
