"""Exact import into an empty, dedicated SQL database, with bounded batches.

Callers supply the verified closed snapshot and the destination connection.
No network discovery, credentials, retry, overwrite, defaults or renumbering.
A lost commit response is uncertain: reconnect and compare the fingerprint;
never call import_database again against a populated destination.
"""
import hashlib
import math
import sqlite3
import struct
import time
from contextlib import suppress

from deploy.cloud.sql_snapshot import page_limit, quoted


class ImportUncertain(RuntimeError):
    pass


def layout(db):
    objects = [tuple(row) for row in db.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
    if any(kind not in ('table', 'index') or not isinstance(sql, str) for kind, _, sql in objects):
        raise ValueError('unsupported_import_schema')
    flags = {row[1]: bool(row[4]) for row in db.execute('PRAGMA table_list') if row[0] == 'main'}
    tables = []
    for kind, name, sql in objects:
        if kind != 'table':
            continue
        if not sql.lstrip().upper().startswith('CREATE TABLE') or name not in flags:
            raise ValueError('unsupported_import_schema')
        fields = [tuple(row) for row in db.execute(f'PRAGMA table_xinfo({quoted(name)})')]
        columns = [row[1] for row in fields if row[6] == 0]
        if not columns or len(columns) > 512:
            raise ValueError('unsupported_import_columns')
        if not flags[name]:
            hidden = next((item for item in ('_rowid_', 'rowid', 'oid')
                           if item not in {field.casefold() for field in columns}), None)
            if hidden is None:
                raise ValueError('unsupported_import_rowid')
            columns.insert(0, hidden)
            order = quoted(hidden)
        else:
            primary = [row[1] for row in sorted(fields, key=lambda row: row[5]) if row[5]]
            if not primary:
                raise ValueError('unsupported_import_primary_key')
            order = ','.join(quoted(item) for item in primary)
        tables.append((name, columns, order))
    metadata = {key: db.execute(f'PRAGMA {key}').fetchone()[0] for key in ('user_version', 'application_id')}
    if any(type(value) is not int or not -(2**31) <= value < 2**31 for value in metadata.values()):
        raise ValueError('unsupported_import_metadata')
    sequence = []
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
        sequence = [tuple(row) for row in db.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name')]
    return objects, tables, metadata, sequence


def encoded(value):
    if value is None:
        return b'n'
    if type(value) is int:
        return b'i' + struct.pack('>q', value)
    if type(value) is float and math.isfinite(value):
        return b'f' + struct.pack('>d', value)
    if isinstance(value, (str, bytes)):
        data = value.encode('utf-8') if isinstance(value, str) else value
        return (b's' if isinstance(value, str) else b'b') + struct.pack('>Q', len(data)) + data
    raise ValueError('unsupported_import_value')


def fingerprint(db, *, check=lambda: None, max_bytes=128 * 1024 * 1024):
    objects, tables, metadata, sequence = layout(db)
    digest, count, size = hashlib.sha256(), 0, 0
    for kind, name, sql in objects:
        for item in (kind, name, sql):
            digest.update(encoded(item))
    for key, value in sorted(metadata.items()):
        digest.update(encoded(key) + encoded(value))
    for row in sequence:
        for value in row:
            digest.update(encoded(value))
    for name, columns, order in tables:
        check()
        digest.update(encoded(name))
        limit, offset = page_limit(db, name, columns), 0
        while True:
            check()
            cursor = db.execute('SELECT ' + ','.join(quoted(item) for item in columns)
                                + f' FROM {quoted(name)} ORDER BY {order} LIMIT ? OFFSET ?', (limit, offset))
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()
            if not rows:
                break
            for row in rows:
                digest.update(b'r')
                for value in row:
                    data = encoded(value)
                    size += len(data)
                    if size > max_bytes:
                        raise ValueError('import_capacity')
                    digest.update(data)
            count += len(rows)
            offset += len(rows)
    return {'sha256': digest.hexdigest(), 'rows': count, 'tables': len(tables), 'content_bytes': size}


def import_database(source, target, *, timeout=600, max_bytes=128 * 1024 * 1024, clock=time.monotonic):
    if (source.in_transaction or target.in_transaction or source is target
            or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 1800
            or type(max_bytes) is not int or not 0 < max_bytes <= 512 * 1024 * 1024):
        raise ValueError('dedicated_idle_import_connections_required')
    deadline = clock() + timeout

    def check():
        if clock() >= deadline:
            raise TimeoutError('database_import_deadline')

    # Check before any change: never DROP, DELETE or replace an existing DB.
    if target.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone():
        raise ValueError('database_import_target_must_be_empty')
    source.execute('BEGIN')
    committed, result = False, None
    try:
        expected = fingerprint(source, check=check, max_bytes=max_bytes)
        objects, tables, metadata, sequence = layout(source)
        if not tables:
            raise ValueError('database_import_source_is_empty')
        if source.execute('PRAGMA quick_check').fetchall() != [('ok',)] or source.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('database_import_source_integrity_failed')
        check()
        target.execute('PRAGMA foreign_keys=OFF')
        target.execute('BEGIN IMMEDIATE')
        for kind, _, sql in objects:
            if kind == 'table':
                target.execute(sql)
        statements = 0
        for name, columns, order in tables:
            names = ','.join(quoted(item) for item in columns)
            cursor = source.execute(f'SELECT {names} FROM {quoted(name)} ORDER BY {order}')
            try:
                while True:
                    check()
                    rows = cursor.fetchmany(min(512, 4096 // len(columns)))
                    if not rows:
                        break
                    # Bound SQL bindings and materialised values. A single large
                    # BLOB is permitted within the existing role byte budget.
                    batches, batch, size = [], [], 0
                    for row in rows:
                        row = tuple(row)
                        amount = sum(len(encoded(item)) for item in row)
                        if batch and size + amount > 512 * 1024:
                            batches.append(batch)
                            batch, size = [], 0
                        batch.append(row)
                        size += amount
                    if batch:
                        batches.append(batch)
                    for batch in batches:
                        check()
                        target.execute(f'INSERT INTO {quoted(name)}({names}) VALUES '
                                       + ','.join('(' + ','.join('?' for _ in columns) + ')' for _ in batch),
                                       tuple(value for row in batch for value in row))
                        statements += 1
            finally:
                cursor.close()
        # Restore the original sequence, including deleted high numbers.
        if target.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
            target.execute('DELETE FROM sqlite_sequence')
            for row in sequence:
                target.execute('INSERT INTO sqlite_sequence VALUES(?,?)', row)
        for kind, _, sql in objects:
            if kind == 'index':
                target.execute(sql)
        for key, value in metadata.items():
            # Turso exposes these header fields read-only. Do not issue an
            # unnecessary forbidden setter when the original value already
            # matches. A differing, non-writable version still aborts, rather
            # than quietly losing metadata or relaxing the final fingerprint.
            if target.execute(f'PRAGMA {key}').fetchone()[0] != value:
                target.execute(f'PRAGMA {key}={value}')
        actual = fingerprint(target, check=check, max_bytes=max_bytes)
        if actual != expected or target.execute('PRAGMA quick_check').fetchall() != [('ok',)] or target.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('database_import_verification_failed')
        check()
        try:
            target.commit()
        except (OSError, sqlite3.Error):
            raise ImportUncertain('database_import_commit_unknown_reconnect_and_compare') from None
        committed = True
        result = {**expected, 'committed': True, 'insert_statements': statements,
                  'overwrote_existing_data': False, 'renumbered': False}
    finally:
        source.rollback()
        if not committed:
            with suppress(OSError, sqlite3.Error):
                target.rollback()  # Preserve an uncertain commit acknowledgement.
    return result
