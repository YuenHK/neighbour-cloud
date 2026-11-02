"""OFFLINE restore helper: preserve current revocations/subscriptions/cursors.

Like current ledger/quota/control restore rules, old application backups must
not revive a revoked site token or a removed subscription. Requires a fresh
stopped-writer receipt and a LOCAL SQLite restore candidate, never a live target.
This file's direct execution runs synthetic self-tests only.
"""
import hashlib
import json
import sqlite3
from datetime import UTC, datetime


def preserve(current, candidate, stop_receipt):
    age = (datetime.now(UTC) - datetime.fromisoformat(stop_receipt['observed_utc'])).total_seconds()
    if (not stop_receipt.get('actual_old_process_exit') or not stop_receipt.get('new_process_maintenance_only')
            or not 0 <= age <= 120 or not isinstance(candidate, sqlite3.Connection)
            or current is candidate or current.in_transaction or candidate.in_transaction):
        raise ValueError('fresh_stopped_writer_and_offline_candidate_required')
    # Missing/unavailable CURRENT registry is a hard failure, never use the old
    # snapshot or treat it as empty. No capability material is decrypted here.
    rows = [tuple(row) for row in current.execute('SELECT namespace,identity,payload FROM cloud_operations '
                                                  'ORDER BY namespace,identity LIMIT 25001').fetchall()]
    if len(rows) > 25000 or sum(len(value.encode()) for row in rows for value in row) > 64*1024*1024:
        raise ValueError('operations_restore_budget')
    for namespace, identity, payload in rows:
        if not isinstance(json.loads(payload), (dict, list, str, int, float, bool)):
            raise ValueError('invalid_current_operations')
    with candidate:
        candidate.execute('CREATE TABLE IF NOT EXISTS cloud_operations(namespace TEXT NOT NULL,'
            'identity TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(namespace,identity))')
        candidate.execute('DELETE FROM cloud_operations')
        candidate.executemany('INSERT INTO cloud_operations VALUES(?,?,?)', rows)
        assert [tuple(row) for row in candidate.execute('SELECT namespace,identity,payload FROM cloud_operations '
                                                       'ORDER BY namespace,identity')] == rows
    return {'current_operations_preserved': True, 'rows': len(rows), 'old_revocations_not_rolled_back': True,
            'sha256': hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()}


if __name__ == '__main__':
    current, old = sqlite3.connect(':memory:'), sqlite3.connect(':memory:')
    schema = 'CREATE TABLE cloud_operations(namespace TEXT,identity TEXT,payload TEXT,PRIMARY KEY(namespace,identity))'
    for db in (current, old):
        db.execute(schema)
    current.execute('INSERT INTO cloud_operations VALUES(?,?,?)', ('patrol-site', 'synthetic', '{"active":false}'))
    old.executemany('INSERT INTO cloud_operations VALUES(?,?,?)', [('patrol-site', 'synthetic', '{"active":true}'),
        ('push-subscription', 'removed', '{"sealed":"old-public-test"}')])
    old.execute('CREATE TABLE resident_marker(text TEXT)')
    old.execute("INSERT INTO resident_marker VALUES('MB842 PUBLIC SYNTHETIC')")
    current.commit(); old.commit()
    proof = {'observed_utc': datetime.now(UTC).isoformat(), 'actual_old_process_exit': True, 'new_process_maintenance_only': True}
    result = preserve(current, old, proof)
    assert old.execute('SELECT payload FROM cloud_operations').fetchall() == [('{"active":false}',)]
    assert old.execute('SELECT text FROM resident_marker').fetchone()[0] == 'MB842 PUBLIC SYNTHETIC'
    try:
        preserve(current, old, {**proof, 'actual_old_process_exit': False})
    except ValueError:
        pass
    else:
        raise AssertionError('unsafe restore not rejected')
    print(json.dumps({**result, 'synthetic_only': True, 'live_restore_performed': False}))
