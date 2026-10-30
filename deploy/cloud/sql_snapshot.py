"""Consistent bounded SQL-to-SQLite recovery snapshot for the cloud candidate.

No live source writes, no filename overwrite and no remote service are used
here. The caller must publish a completion marker only after this returns.
The deadline is cooperative, in addition to the driver's network timeout.
"""
import os
import sqlite3
import time
from pathlib import Path


def quoted(name):
    if not isinstance(name, str) or not name or '\x00' in name:
        raise ValueError('invalid_snapshot_identifier')
    return '"' + name.replace('"', '""') + '"'


def snapshot(source, destination, *, timeout=20, max_bytes=128 * 1024 * 1024,
             clock=time.monotonic):
    if (not 0 < timeout <= 120 or not 0 < max_bytes <= 512 * 1024 * 1024
            or source.in_transaction):
        raise ValueError('snapshot_requires_idle_dedicated_connection')
    destination = Path(destination).absolute()
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError('snapshot_destination_requires_existing_directory')
    if destination.exists() or destination.is_symlink():
        raise ValueError('snapshot_destination_must_be_new')
    deadline = clock() + timeout

    def check():
        if clock() > deadline:
            raise ValueError('snapshot_deadline')

    target = None
    count = size = 0
    source.execute('BEGIN')
    try:
        check()
        schema = source.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                                "ORDER BY type,name").fetchall()
        if any(row[0] not in ('table', 'index') or not isinstance(row[2], str) for row in schema):
            raise ValueError('unsupported_snapshot_schema')
        tables = [row for row in schema if row[0] == 'table']
        if any(not row[2].lstrip().upper().startswith('CREATE TABLE') for row in tables):
            raise ValueError('unsupported_snapshot_schema')
        without_rowid = {row[1]: bool(row[4]) for row in source.execute('PRAGMA table_list') if row[0] == 'main'}
        metadata = {name: source.execute(f'PRAGMA {name}').fetchone()[0]
                    for name in ('user_version', 'application_id')}
        if any(type(value) is not int or not -(2**31) <= value < 2**31 for value in metadata.values()):
            raise ValueError('invalid_snapshot_metadata')
        # Exclusive create before SQLite opens the file. A failed/incomplete
        # snapshot is deliberately left present, never silently overwritten.
        with destination.open('xb'):
            pass
        if os.name == 'posix':
            destination.chmod(0o600)
        target = sqlite3.connect(destination)
        target.execute('PRAGMA trusted_schema=OFF')
        target.execute('PRAGMA foreign_keys=OFF')
        target.set_progress_handler(lambda: int(clock() > deadline), 1000)
        with target:
            for _, name, sql in tables:
                check()
                target.execute(sql)
                fields = source.execute(f'PRAGMA table_xinfo({quoted(name)})').fetchall()
                columns = [row[1] for row in fields if row[6] == 0]
                if not columns:
                    raise ValueError('unsupported_snapshot_columns')
                names = ','.join(quoted(column) for column in columns)
                primary = [row[1] for row in sorted(fields, key=lambda row: row[5]) if row[5]]
                ordering = ','.join(quoted(column) for column in primary) if primary else '_rowid_'
                if name not in without_rowid:
                    raise ValueError('unsupported_snapshot_table_flags')
                if not without_rowid[name]:
                    existing = {column.casefold() for column in columns}
                    hidden = next((alias for alias in ('_rowid_', 'rowid', 'oid') if alias not in existing), None)
                    if hidden is None:
                        raise ValueError('unsupported_snapshot_rowid_aliases')
                    columns.insert(0, hidden)
                    names = ','.join(quoted(column) for column in columns)
                    ordering = quoted(hidden)
                offset = 0
                while True:
                    check()
                    cursor = source.execute(f'SELECT {names} FROM {quoted(name)} ORDER BY {ordering} LIMIT ? OFFSET ?',
                                            (128, offset))
                    try:
                        rows = cursor.fetchall()
                    finally:
                        cursor.close()
                    if not rows:
                        break
                    # Bound materialised content as well as final SQLite size.
                    size += sum(len(value) if isinstance(value, (bytes, str)) else 8
                                for row in rows for value in row if value is not None)
                    if size > max_bytes:
                        raise ValueError('snapshot_capacity')
                    target.executemany(f'INSERT INTO {quoted(name)}({names}) '
                                       f'VALUES ({",".join("?" for _ in columns)})', [tuple(row) for row in rows])
                    count += len(rows)
                    offset += len(rows)
            # Preserve AUTOINCREMENT after deletions; never renumber a case.
            if source.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
                target.execute('DELETE FROM sqlite_sequence')
                target.executemany('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)',
                                   [tuple(row) for row in source.execute('SELECT name,seq FROM sqlite_sequence')])
            for kind, _, sql in schema:
                check()
                if kind == 'index':
                    target.execute(sql)
            for name, value in metadata.items():
                target.execute(f'PRAGMA {name}={value}')
            check()
        if target.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('snapshot_integrity_failed')
        if target.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('snapshot_foreign_key_check_failed')
        check()
        if destination.stat().st_size > max_bytes:
            raise ValueError('snapshot_capacity')
        return {'tables': len(tables), 'rows': count, 'integrity_verified': True,
                'consistent_read_transaction': True}
    finally:
        if target is not None:
            target.close()
        source.rollback()
