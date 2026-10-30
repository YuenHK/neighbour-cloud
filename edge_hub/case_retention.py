"""90 days after case completion: erase private fields in managed live/backup DBs.

Preserve case numbers/idempotency tombstones, open cases, explicit memories and
robot safety logs. Historical backup fingerprints change with a recorded receipt.
"""
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

FIELDS = {'location', 'message', 'contact', 'assignee', 'note', 'profile', 'unit'}


def managed_backups(runtime_root, table):
    root = Path(runtime_root).resolve()
    result = []
    candidates = sorted([*root.rglob('*.sqlite3'), *root.rglob('*.db')])
    if len(candidates) > 256:
        raise ValueError('backup_inventory_requires_review')
    live_names = {'service-desk.sqlite3', 'events.sqlite3', 'estate-information.sqlite3',
                  'assistant-memory.sqlite3', 'staff-access.sqlite3'}
    for path in candidates:
        if path.parent == root and path.name in live_names:
            continue
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('backup_inventory_requires_review')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                result.append(path)
    return result


def receipt(root, path, before, count):
    directory = Path(root)/'retention-receipts'
    directory.mkdir(exist_ok=True)
    record = {'schema': 'retention-v1', 'at_ms': int(time.time()*1000),
              'backup_relative': path.relative_to(Path(root)).as_posix(), 'before_sha256': before,
              'after_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'expired_record_count': count}
    with (directory/(str(time.time_ns())+'.json')).open('x', encoding='utf-8') as output:
        json.dump(record, output)


def scrub(connection, identities):
    connection.execute('PRAGMA trusted_schema=OFF')
    connection.execute('PRAGMA secure_delete=ON')
    columns = {row[1] for row in connection.execute('PRAGMA table_info(service_cases)')}
    if not {'id', 'status', 'message', 'contact', 'location', 'updated_at_ms'} <= columns:
        raise ValueError('unrecognised_case_backup')
    found = sorted(columns & FIELDS)
    activity = {row[1] for row in connection.execute('PRAGMA table_info(service_case_activity)')}
    with connection:
        connection.execute('CREATE TABLE IF NOT EXISTS case_privacy_expiry (id TEXT PRIMARY KEY,erased_at_ms INTEGER NOT NULL)')
        for identity in identities:
            row = connection.execute('SELECT status FROM service_cases WHERE id=?', (identity,)).fetchone()
            if row is None:
                continue
            # A historical backup may show the case before completion; it still
            # contains the same expired person's data and must be scrubbed too.
            connection.execute('UPDATE service_cases SET '+','.join(f'{key}=?' for key in found)+' WHERE id=?',
                               (*('已按保存期限清除' if key == 'message' else '' for key in found), identity))
            if 'case_id' in activity:
                for key in ('note', 'assignee'):
                    if key in activity:
                        connection.execute(f"UPDATE service_case_activity SET {key}='' WHERE case_id=?", (identity,))
            connection.execute('INSERT OR IGNORE INTO case_privacy_expiry VALUES (?,?)', (identity, int(time.time()*1000)))


def expire_cases(cases, runtime_root, *, now_ms=None):
    root = Path(runtime_root).resolve()
    cutoff = (int(time.time()*1000) if now_ms is None else now_ms)-90*86400000
    with cases.lock:
        cases.db.execute('CREATE TABLE IF NOT EXISTS case_privacy_expiry (id TEXT PRIMARY KEY,erased_at_ms INTEGER NOT NULL)')
        cases.db.commit()
        identities = [row[0] for row in cases.db.execute(
            "SELECT id FROM service_cases WHERE status='resolved' AND updated_at_ms<=? "
            'AND id NOT IN (SELECT id FROM case_privacy_expiry) ORDER BY updated_at_ms LIMIT 100', (cutoff,))]
        if not identities:
            return {'erased_cases': 0, 'managed_backups': 0}
        backups = managed_backups(root, 'service_cases')
        if len(backups) > 32:
            raise ValueError('backup_inventory_requires_review')
        # Validate every backup before any private field is changed.
        for path in backups:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
                cols = {row[1] for row in db.execute('PRAGMA table_info(service_cases)')}
                if not {'id', 'status', 'message', 'contact', 'location', 'updated_at_ms'} <= cols:
                    raise ValueError('unrecognised_case_backup')
        for path in backups:
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with closing(sqlite3.connect(path, timeout=2)) as db:
                scrub(db, identities)
                db.execute('VACUUM')
            receipt(root, path, before, len(identities))
        scrub(cases.db, identities)
        # Compact SQLite free pages only after the transaction has committed.
        cases.db.execute('VACUUM')
    return {'erased_cases': len(identities), 'managed_backups': len(backups)}


def expire_event_photos(events, data_root, *, now_ms=None, runtime_root=None):
    root = (Path(data_root)/'events').resolve()
    now = int(time.time()*1000) if now_ms is None else now_ms
    cutoff = now-90*86400000
    with events._lock:
        db = events._connection
        due = db.execute("SELECT e.id FROM events e JOIN event_completion c ON c.event_id=e.id "
                         "WHERE c.completed_at_ms<=? AND e.status IN ('resolved','false_positive') "
                         "AND e.details_json NOT LIKE '%\"retention_erased\": true%' LIMIT 100", (cutoff,)).fetchall()
        if due and runtime_root is not None:
            for path in managed_backups(runtime_root, 'events'):
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                with closing(sqlite3.connect(path, timeout=2)) as backup:
                    backup.execute('PRAGMA trusted_schema=OFF')
                    backup.execute('PRAGMA secure_delete=ON')
                    with backup:
                        for item in due:
                            backup.execute('UPDATE events SET evidence=NULL,zone=?,details_json=? WHERE id=?',
                                ('已按保存期限清除', json.dumps({'retention_erased': True, 'erased_at_ms': now}), item[0]))
                    backup.execute('VACUUM')
                receipt(Path(runtime_root).resolve(), path, before, len(due))
        db.execute('PRAGMA secure_delete=ON')
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS expired_event_evidence (path TEXT PRIMARY KEY)')
            rows = db.execute("SELECT e.* FROM events e JOIN event_completion c ON c.event_id=e.id "
                              "WHERE c.completed_at_ms<=? AND e.status IN ('resolved','false_positive') LIMIT 100", (cutoff,)).fetchall()
            for row in rows:
                details = json.loads(row['details_json'])
                if details.get('retention_erased'):
                    continue
                paths = [row['evidence']] if row['evidence'] else []
                paths += [item['path'] for item in details.get('photos', []) if isinstance(item, dict) and isinstance(item.get('path'), str)]
                for relative in set(paths):
                    target = (Path(data_root)/relative).resolve()
                    if not target.is_relative_to(root):
                        raise ValueError('unsafe_expiry_photo_path')
                    db.execute('INSERT OR IGNORE INTO expired_event_evidence VALUES (?)', (relative,))
                db.execute('UPDATE events SET evidence=NULL,zone=?,details_json=? WHERE id=?',
                           ('已按保存期限清除', json.dumps({'retention_erased': True, 'erased_at_ms': now}), row['id']))
        queue = [row[0] for row in db.execute('SELECT path FROM expired_event_evidence LIMIT 300')]
        for relative in queue:
            unresolved = Path(data_root)/relative
            target = unresolved.resolve()
            if unresolved.is_symlink() or not target.is_relative_to(root):
                raise ValueError('unsafe_expiry_photo_path')
            # Do not erase a shared path while another active event references it.
            if db.execute('SELECT 1 FROM events WHERE evidence=? LIMIT 1', (relative,)).fetchone():
                continue
            if db.execute("SELECT 1 FROM events e,json_each(json_extract(e.details_json,'$.photos')) p "
                          "WHERE json_extract(p.value,'$.path')=? LIMIT 1", (relative,)).fetchone():
                continue
            target.unlink(missing_ok=True)
            with db:
                db.execute('DELETE FROM expired_event_evidence WHERE path=?', (relative,))
    return {'expired_event_candidates': len(rows), 'photo_queue_checked': len(queue)}
