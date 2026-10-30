import hashlib
import json
import sqlite3

import pytest

from deploy.cloud.backup_store import DAY, ROLES, BackupStore, BackupUncertain
from deploy.cloud.deletion_ledger import ZERO
from deploy.cloud.libsql_connection import Connection

KEY = b'PUBLIC-SYNTHETIC-BACKUP-KEY-ONLY-' + b'x' * 16
HEAD = {'seq': 0, 'digest': ZERO, 'signature': ZERO}


@pytest.fixture(params=['sqlite', 'libsql'])
def backups(request):
    if request.param == 'libsql':
        libsql = pytest.importorskip('libsql')
        db = Connection(libsql.connect(':memory:'), libsql.Error)
    else:
        db = sqlite3.connect(':memory:')
    store = BackupStore(db, KEY, initialize=True)
    yield store
    db.close()


@pytest.fixture
def files(tmp_path):
    root = tmp_path / 'closed'
    root.mkdir()
    paths = {}
    for role in ROLES:
        path = root / (role + '.sqlite3')
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE records(id TEXT,body BLOB)')
            content = b'SYNTHETIC-' + role.encode() + b'\x00\xff'
            if role == 'photos':
                content *= 30000  # Real multiple-chunk file, bounded streaming.
            db.execute('INSERT INTO records VALUES(?,?)', ('MB842-' + role, content))
        paths[role] = path
    return paths


def publish(store, files, *, day=1, identity='a' * 32):
    return store.publish(identity, files, created_ms=day * DAY,
                         ledger_checkpoint=HEAD, source_fence_verified=True)


def test_eight_closed_stores_publish_readback_reopen_and_private_download(backups, files, tmp_path):
    before = {role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in files.items()}
    result = publish(backups, files)
    assert result['completed'] and result['stores'] == 8 and not result['ledger_or_key_included']
    reopened = BackupStore(backups.db, KEY)
    manifest = reopened.manifest('a' * 32)
    assert manifest['files']['photos']['parts'] >= 2
    assert set(manifest['files']) == ROLES and 'deletion_ledger' not in manifest['files']
    recovered = reopened.download('a' * 32, tmp_path / 'new-recovery')
    assert recovered['download_verified'] and not recovered['cutover_ready'] and not recovered['production_replaced']
    for role, path in recovered['files'].items():
        from pathlib import Path

        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == before[role]
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT id FROM records').fetchone()[0] == 'MB842-' + role
    assert before == {role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in files.items()}
    assert reopened.status()['completed'] == 1 and reopened.status()['pending'] == 0


@pytest.mark.parametrize('change', ['missing_role', 'ledger_included', 'no_fence', 'active_sidecar'])
def test_incomplete_unfenced_or_active_files_never_get_a_backup_catalog(backups, files, change):
    args = {'source_fence_verified': True}
    if change == 'missing_role':
        files.pop('usage')
    elif change == 'ledger_included':
        files['deletion_ledger'] = files['controls']
    elif change == 'no_fence':
        args['source_fence_verified'] = False
    else:
        from pathlib import Path

        Path(str(files['cases']) + '-wal').write_bytes(b'SYNTHETIC-ACTIVE')
    with pytest.raises(ValueError):
        backups.publish('a' * 32, files, created_ms=DAY, ledger_checkpoint=HEAD, **args)
    assert backups.status()['completed'] == backups.status()['pending'] == 0


@pytest.mark.parametrize('damage', ['content', 'manifest', 'signature', 'missing_chunk', 'extra_chunk'])
def test_corrupt_data_or_manifest_cannot_be_downloaded_as_ready(backups, files, tmp_path, damage):
    publish(backups, files)
    with backups.db:
        if damage == 'content':
            backups.db.execute('UPDATE cloud_backup_chunks SET content=? WHERE role=? AND part=0', (b'wrong', 'memory'))
        elif damage in ('manifest', 'signature'):
            if damage == 'signature':
                backups.db.execute('UPDATE cloud_backup_sets SET signature=?', ('f' * 64,))
            else:
                item = backups.manifest('a' * 32)
                item['files']['usage']['sha256'] = 'f' * 64
                backups.db.execute('UPDATE cloud_backup_sets SET manifest=?', (json.dumps(item),))
        elif damage == 'missing_chunk':
            backups.db.execute('DELETE FROM cloud_backup_chunks WHERE role=?', ('usage',))
        else:
            backups.db.execute('INSERT INTO cloud_backup_chunks VALUES(?,?,?,?)', ('a' * 32, 'extra', 1, b'x'))
    with pytest.raises(ValueError):
        backups.download('a' * 32, tmp_path / 'unaccepted')


def test_old_backups_are_rotated_only_after_today_succeeds_and_no_pending(backups, files):
    for day in range(1, 9):
        publish(backups, files, day=day, identity=f'{day:032x}')
    with pytest.raises(ValueError, match='fresh_completed'):
        backups.rotate(now_ms=9 * DAY)
    assert backups.status()['completed'] == 8
    result = backups.rotate(now_ms=8 * DAY)
    assert result == {'rotated_managed_backups': 1, 'kept': 7}
    assert backups.db.execute('SELECT COUNT(*) FROM cloud_backup_chunks WHERE backup_id=?', (f'{1:032x}',)).fetchone()[0] == 0
    with pytest.raises(ValueError, match='already_exists'):
        publish(backups, files, day=8, identity='b' * 32)
    assert backups.db.execute('SELECT operation FROM cloud_backup_receipts').fetchone()[0] == 'managed_daily_rotation'


def test_lost_initial_commit_ack_remains_pending_and_is_not_blindly_retried(files):
    db = sqlite3.connect(':memory:')
    BackupStore(db, KEY, initialize=True)

    class LostAck:
        def __getattr__(self, name):
            return getattr(db, name)

        def commit(self):
            db.commit()
            raise OSError('synthetic lost commit acknowledgement')

    store = BackupStore(LostAck(), KEY)
    with pytest.raises(BackupUncertain, match='read_status'):
        publish(store, files)
    assert store.status()['pending'] == 1 and store.status()['completed'] == 0
    with pytest.raises(ValueError, match='already_exists'):
        publish(store, files)
    with pytest.raises(ValueError, match='fresh_completed'):
        store.rotate(now_ms=DAY)
    db.close()


def test_lost_final_commit_ack_reports_unknown_but_readback_proves_ready(files):
    db = sqlite3.connect(':memory:')
    BackupStore(db, KEY, initialize=True)

    class LostFinal:
        final = False

        def __getattr__(self, name):
            return getattr(db, name)

        def execute(self, sql, parameters=()):
            if sql.startswith("UPDATE cloud_backup_sets SET status='ready'"):
                self.final = True
            return db.execute(sql, parameters)

        def commit(self):
            db.commit()
            if self.final:
                raise OSError('synthetic lost acknowledgement after publication')

    store = BackupStore(LostFinal(), KEY)
    with pytest.raises(BackupUncertain):
        publish(store, files)
    assert store.status()['completed'] == 1 and store.status()['pending'] == 0
    assert store.manifest('a' * 32)['files']['usage']['sha256']
    with pytest.raises(ValueError, match='already_exists'):
        publish(store, files)
    db.close()


def test_partial_chunk_failure_is_pending_and_never_a_completed_backup(files):
    db = sqlite3.connect(':memory:')
    BackupStore(db, KEY, initialize=True)

    class BrokenChunks:
        count = 0

        def __getattr__(self, name):
            return getattr(db, name)

        def execute(self, sql, parameters=()):
            if sql.startswith('INSERT INTO cloud_backup_chunks'):
                self.count += 1
                if self.count == 3:
                    raise OSError('synthetic network outage')
            return db.execute(sql, parameters)

    store = BackupStore(BrokenChunks(), KEY)
    with pytest.raises(OSError):
        publish(store, files)
    assert store.status()['pending'] == 1 and store.status()['completed'] == 0
    with pytest.raises(ValueError, match='completed_backup_required'):
        store.manifest('a' * 32)
    with pytest.raises(ValueError, match='already_exists'):
        publish(store, files)
    db.close()


def test_retention_rewrites_backup_bytes_using_live_ledger_without_resetting_usage_or_memory(backups, files, tmp_path):
    from deploy.cloud.deletion_ledger import DeletionLedger
    from deploy.cloud.photo_store import PhotoStore

    for role in ('cases', 'events', 'photos'):
        with sqlite3.connect(files[role]) as db:
            db.execute('DROP TABLE records')
            if role == 'cases':
                db.execute('CREATE TABLE service_cases(id TEXT PRIMARY KEY,status TEXT,message TEXT,location TEXT,contact TEXT)')
                db.execute('CREATE TABLE service_case_activity(case_id TEXT,note TEXT,assignee TEXT)')
                db.execute('INSERT INTO service_cases VALUES(?,?,?,?,?)', ('expired-case', 'resolved', 'PRIVATE-SYNTHETIC-HELP', 'PRIVATE-UNIT', 'PRIVATE-CALL'))
                db.execute('INSERT INTO service_case_activity VALUES(?,?,?)', ('expired-case', 'PRIVATE-STAFF-NOTE', 'PRIVATE-NAME'))
            elif role == 'events':
                db.execute('CREATE TABLE events(id TEXT PRIMARY KEY,zone TEXT,evidence TEXT,details_json TEXT)')
                db.execute('INSERT INTO events VALUES(?,?,?,?)', ('expired-event', 'PRIVATE-ZONE', 'events/old-blurred.jpg', '{}'))
            else:
                PhotoStore(db)
                db.execute('CREATE TABLE native_evidence_blobs(key TEXT PRIMARY KEY,digest TEXT,content BLOB)')
                db.execute('CREATE TABLE native_evidence_bindings(event_id TEXT,key TEXT)')
                db.execute('CREATE TABLE native_evidence_missing(event_id TEXT,key TEXT)')
                db.execute('INSERT INTO native_evidence_blobs VALUES(?,?,?)', ('events/old-blurred.jpg', 'x', b'PRIVATE-LEGACY-PHOTO'))
                db.execute('INSERT INTO native_evidence_bindings VALUES(?,?)', ('expired-event', 'events/old-blurred.jpg'))
    live = sqlite3.connect(':memory:')
    ledger = DeletionLedger(live, KEY, initialize=True)
    backups.publish('a' * 32, files, created_ms=DAY, ledger_checkpoint=ledger.checkpoint(), source_fence_verified=True)
    old = backups.manifest('a' * 32)
    # This receipt was added AFTER the backup. An old embedded checkpoint must
    # never allow the private content back into either a backup or live store.
    ledger.append([{'kind': 'case', 'target': 'expired-case', 'revision': 2, 'erased_ms': 2 * DAY},
                   {'kind': 'event', 'target': 'expired-event', 'revision': 1, 'erased_ms': 2 * DAY}])
    result = backups.reconcile_erasure('a' * 32, ledger=ledger, scratch_root=tmp_path,
                                      now_ms=2 * DAY, writer_fence=lambda: True)
    assert result['reconciled'] and result['durable_receipt'] and result['usage_controls_memory_unchanged']
    current = backups.manifest('a' * 32)
    assert current['created_ms'] == old['created_ms'] == DAY
    for role in ('usage', 'controls', 'memory', 'journal', 'estate'):
        assert current['files'][role] == old['files'][role]
    recovered = backups.download('a' * 32, tmp_path / 'scrubbed')
    for role in ('cases', 'events', 'photos'):
        from pathlib import Path

        contents = Path(recovered['files'][role]).read_bytes()
        assert b'PRIVATE-' not in contents
    assert b'PRIVATE-SYNTHETIC-HELP' in files['cases'].read_bytes()  # Closed source was never overwritten.
    assert backups.db.execute('SELECT operation FROM cloud_backup_receipts').fetchone()[0] == 'retention_reconcile'
    assert ledger.checkpoint() == current['ledger_checkpoint_at_backup']
    assert backups.reconcile_erasure('a' * 32, ledger=ledger, scratch_root=tmp_path,
                                     now_ms=2 * DAY, writer_fence=lambda: True)['reconciled'] is False
    live.close()
