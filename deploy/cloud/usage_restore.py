"""Prepare a NEW usage DB without rolling conservative reservations backwards.

The explicit live cloud store must remain authoritative and independently
available. This is not a whole-system restore, a writer fence or a cutover.
Never call it against production from a scheduled heartbeat.
"""
import hashlib
import json
import math
import re
import sqlite3
import time
from contextlib import closing
from datetime import date
from pathlib import Path

from deploy.cloud.closed_backup import unchanged_closed_backup
from deploy.cloud.runtime_storage import RuntimeStorage
from deploy.cloud.sql_snapshot import snapshot
from edge_hub.cloud_allowance import LIMITS

MAX_RECORDS = 50_000


class UsageRestoreError(ValueError):
    pass


def read_usage(db, check):
    if db.in_transaction:
        raise UsageRestoreError('usage_restore_requires_dedicated_connection')
    values = {}
    with db:
        db.execute('BEGIN')
        schema = db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if ({row[1] for row in schema if row[0] == 'table'} != {'usage'}
                or any(row[0] not in ('table', 'index') for row in schema)):
            raise UsageRestoreError('usage_restore_schema_requires_review')
        fields = db.execute('PRAGMA table_info(usage)').fetchall()
        if ([(row[1], row[2].upper(), row[3], row[5]) for row in fields]
                != [('meter', 'TEXT', 1, 1), ('period', 'TEXT', 1, 2), ('amount', 'INTEGER', 1, 0)]):
            raise UsageRestoreError('usage_restore_schema_requires_review')
        metadata = tuple(db.execute(f'PRAGMA {name}').fetchone()[0] for name in ('user_version', 'application_id'))
        if any(type(value) is not int or not -(2**31) <= value < 2**31 for value in metadata):
            raise UsageRestoreError('usage_restore_schema_requires_review')
        cursor = db.execute('SELECT meter,period,amount FROM usage ORDER BY meter,period')
        try:
            while rows := cursor.fetchmany(128):
                check()
                for meter, period, amount in rows:
                    if (not isinstance(meter, str) or meter not in LIMITS or not isinstance(period, str)
                            or type(amount) is not int or not 0 <= amount < 2**63 or (meter, period) in values):
                        raise UsageRestoreError('usage_restore_counters_require_review')
                    monthly = LIMITS[meter][0] == 'month'
                    if not re.fullmatch(r'\d{4}-\d{2}' + ('' if monthly else r'-\d{2}'), period):
                        raise UsageRestoreError('usage_restore_period_requires_review')
                    date.fromisoformat(period + '-01' if monthly else period)
                    values[meter, period] = amount
                    if len(values) > MAX_RECORDS:
                        raise UsageRestoreError('usage_restore_record_budget')
        finally:
            cursor.close()
    check()
    return values, metadata


def fingerprint(state):
    values, metadata = state
    data = {'metadata': metadata, 'counters': [[*key, values[key]] for key in sorted(values)]}
    return hashlib.sha256(json.dumps(data, separators=(',', ':'), sort_keys=True).encode()).hexdigest()


def recover_usage(backup, destination, *, expected_sha256, storage, timeout=30, clock=time.monotonic):
    if (not isinstance(storage, RuntimeStorage) or type(timeout) not in (int, float)
            or not math.isfinite(timeout) or not 0 < timeout <= 120 or not callable(clock)):
        raise UsageRestoreError('usage_restore_configuration_required')
    deadline = clock() + timeout

    def check():
        if clock() >= deadline:
            raise UsageRestoreError('usage_restore_deadline')

    def live_state():
        path = storage.settings_root / 'cloud-usage.sqlite3'
        with closing(storage.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            return read_usage(db, check)

    def sha(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    try:
        backup, destination = Path(backup).absolute(), Path(destination).absolute()
        if (not isinstance(expected_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_sha256)
                or not backup.is_file() or backup.stat().st_size > 128 * 1024 * 1024
                or any(path.is_symlink() for path in (backup, *backup.parents, destination, *destination.parents))
                or not destination.parent.is_dir() or destination.exists()
                or any(Path(str(backup) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))
                or sha(backup) != expected_sha256):
            raise UsageRestoreError('closed_verified_usage_backup_and_new_destination_required')
        current = live_state()  # Missing/unavailable live state fails before creating output.
        # Only this closed, hash-checked file is immutable; live cloud reads
        # retain their normal read transactions. Avoid making input sidecars.
        with closing(sqlite3.connect(backup.as_uri() + '?mode=ro&immutable=1', uri=True)) as source:
            source.execute('PRAGMA trusted_schema=OFF')
            original = read_usage(source, check)
            if original[1] != current[1]:
                raise UsageRestoreError('usage_restore_schema_version_requires_review')
            merged = dict(original[0])
            for key, amount in current[0].items():
                merged[key] = max(merged.get(key, 0), amount)
            if len(merged) > MAX_RECORDS:
                raise UsageRestoreError('usage_restore_record_budget')
            check()
            snapshot(source, destination, timeout=max(.001, deadline-clock()), clock=clock)
        with closing(sqlite3.connect(destination)) as target:
            target.execute('PRAGMA trusted_schema=OFF')
            target.set_progress_handler(lambda: int(clock() >= deadline), 1000)
            if read_usage(target, check) != original:
                raise UsageRestoreError('usage_restore_backup_changed')
            with target:
                target.execute('BEGIN IMMEDIATE')
                target.executemany('INSERT INTO usage VALUES(?,?,?) ON CONFLICT(meter,period) '
                    'DO UPDATE SET amount=excluded.amount', [(*key, merged[key]) for key in sorted(merged)])
            if read_usage(target, check) != (merged, current[1]):
                raise UsageRestoreError('usage_restore_merge_failed')
            if (target.execute('PRAGMA quick_check').fetchall() != [('ok',)]
                    or target.execute('PRAGMA foreign_key_check').fetchall()):
                raise UsageRestoreError('usage_restore_integrity_failed')
        if live_state() != current:
            raise UsageRestoreError('usage_restore_live_changed')
        if not unchanged_closed_backup(backup, expected_sha256):
            raise UsageRestoreError('usage_restore_backup_changed')
        check()
        result = {'prepared': True, 'cutover_ready': False, 'production_replaced': False,
                  'official_balance_verified': False, 'counter_count': len(merged),
                  'live_fingerprint': fingerprint(current), 'sha256': sha(destination)}
        check()
        return result
    except UsageRestoreError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error):
        raise UsageRestoreError('usage_restore_requires_review') from None
