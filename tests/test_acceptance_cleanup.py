"""Synthetic only: explicit purge receipts survive restore without touching controls."""
import sqlite3

from deploy.cloud.backup_store import ROLES, BackupStore
from deploy.cloud.deletion_ledger import DeletionLedger
from deploy.cloud.retention_restore import reconcile


def test_purge_case_restoration_removes_business_rows_but_retains_number_sequence():
    db=sqlite3.connect(':memory:')
    db.executescript('''CREATE TABLE service_cases(id TEXT PRIMARY KEY,status TEXT,message TEXT,location TEXT,contact TEXT);
    CREATE TABLE service_case_numbers(ordinal INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT UNIQUE);
    CREATE TABLE service_case_activity(id INTEGER PRIMARY KEY,case_id TEXT,note TEXT);
    CREATE TABLE resident_session_turns(seq INTEGER PRIMARY KEY,case_id TEXT,fingerprint TEXT);
    INSERT INTO service_cases VALUES('old','new','private','unit','phone');
    INSERT INTO service_case_numbers(case_id) VALUES('old');
    INSERT INTO service_case_activity VALUES(1,'old','private');
    INSERT INTO resident_session_turns VALUES(1,'old','hash');''')
    records=[{'kind':'case_purge','target':'old','revision':1,'erased_ms':123}]
    ledger=DeletionLedger(sqlite3.connect(':memory:'),b'x'*32,initialize=True)
    ledger.append(records);assert ledger.records(ledger.checkpoint())==records
    with db:assert reconcile(db,'cases',records)==1
    assert db.execute('SELECT COUNT(*) FROM service_cases').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM service_case_activity').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM resident_session_turns').fetchone()[0]==0
    with db:db.execute("INSERT INTO service_case_numbers(case_id) VALUES('new')")
    assert db.execute("SELECT ordinal FROM service_case_numbers WHERE case_id='new'").fetchone()[0]==2
    # Old offline snapshots must obey the current independent purge receipt too.
    with db:db.execute("INSERT INTO service_cases VALUES('old','new','revived','unit','phone')")
    with db:assert reconcile(db,'cases',ledger.records(ledger.checkpoint()))==1
    with db:assert reconcile(db,'cases',records)==0

def test_event_purge_reconciliation_removes_old_event_and_photo_bindings():
    event=sqlite3.connect(':memory:')
    event.executescript('''CREATE TABLE events(id TEXT PRIMARY KEY,zone TEXT,evidence TEXT,details_json TEXT);
    CREATE TABLE event_completion(event_id TEXT PRIMARY KEY,completed_at_ms INTEGER);
    INSERT INTO events VALUES('old','private','file','{}'); INSERT INTO event_completion VALUES('old',1);''')
    records=[{'kind':'event_purge','target':'old','revision':1,'erased_ms':123}]
    with event:assert reconcile(event,'events',records)==1
    assert event.execute('SELECT COUNT(*) FROM event_completion').fetchone()[0]==0
    photo=sqlite3.connect(':memory:')
    photo.executescript('''CREATE TABLE cloud_photos(key TEXT PRIMARY KEY,event_id TEXT,content BLOB,digest TEXT);
    CREATE TABLE cloud_photo_tombstones(key TEXT PRIMARY KEY,event_id TEXT,erased_ms INTEGER);
    INSERT INTO cloud_photos VALUES('photo','old',x'0102','hash');''')
    with photo:assert reconcile(photo,'photos',records)==1
    assert photo.execute('SELECT COUNT(*) FROM cloud_photos').fetchone()[0]==0
    assert photo.execute('SELECT event_id FROM cloud_erased_events').fetchone()[0]=='old'
    with photo:assert reconcile(photo,'photos',records)==0

def test_case_purge_removes_only_corresponding_case_photos_and_preserves_model_and_map_settings():
    estate=sqlite3.connect(':memory:')
    estate.executescript('''CREATE TABLE cloud_operations(namespace TEXT,identity TEXT,payload TEXT);
    INSERT INTO cloud_operations VALUES('resident-case-photo-v1','old','secret');
    INSERT INTO cloud_operations VALUES('patrol-map-v1','map','map');
    INSERT INTO cloud_operations VALUES('vroid_library','account','encrypted');''')
    with estate:assert reconcile(estate,'estate',[{'kind':'case_purge','target':'old','revision':1,'erased_ms':123}])==1
    assert estate.execute('SELECT COUNT(*) FROM cloud_operations').fetchone()[0]==2


def test_large_purge_is_batched_and_keeps_shared_image_until_final_owner():
    db=sqlite3.connect(':memory:')
    db.executescript('''CREATE TABLE cloud_photos(key TEXT PRIMARY KEY,event_id TEXT,content BLOB,digest TEXT);
    CREATE TABLE cloud_photo_tombstones(key TEXT PRIMARY KEY,event_id TEXT,erased_ms INTEGER);
    CREATE TABLE native_evidence_blobs(key TEXT PRIMARY KEY,digest TEXT,content BLOB);
    CREATE TABLE native_evidence_bindings(event_id TEXT,key TEXT);
    CREATE TABLE native_evidence_missing(event_id TEXT,key TEXT);
    INSERT INTO native_evidence_blobs VALUES('shared','hash',x'0102');
    INSERT INTO native_evidence_bindings VALUES('survivor','shared');''')
    db.executemany('INSERT INTO native_evidence_bindings VALUES(?,?)',[(f'e{i}','shared') for i in range(706)])
    db.commit();statements=[];db.set_trace_callback(statements.append)
    records=[{'kind':'event_purge','target':f'e{i}','revision':1,'erased_ms':123} for i in range(706)]
    with db:assert reconcile(db,'photos',records)==706
    assert len(statements)<45  # Four bounded batches; no 706 remote PRAGMAs/deletes.
    assert db.execute('SELECT COUNT(*) FROM native_evidence_blobs').fetchone()[0]==1
    assert db.execute('SELECT COUNT(*) FROM cloud_erased_events').fetchone()[0]==706
    with db:reconcile(db,'photos',[{'kind':'event_purge','target':'survivor','revision':1,'erased_ms':124}])
    assert db.execute('SELECT COUNT(*) FROM native_evidence_blobs').fetchone()[0]==0


def test_large_signed_ledger_batch_keeps_original_time_on_unknown_commit_retry():
    db=sqlite3.connect(':memory:');ledger=DeletionLedger(db,b'x'*32,initialize=True)
    records=[{'kind':'event_purge','target':f'e{i}','revision':1,'erased_ms':123} for i in range(706)]
    statements=[];db.set_trace_callback(statements.append)
    first=ledger.append(records)
    assert first['seq']==706 and len(statements)<20
    # A lost acknowledgement is resolved from the same identities; no new rows.
    assert ledger.append([{**row,'erased_ms':999} for row in records])==first
    assert ledger.records(first)==records


def test_managed_backup_purge_survives_independent_download_and_keeps_other_stores(tmp_path):
    key=b'PUBLIC-SYNTHETIC-PURGE-KEY-ONLY-xxx'
    ledger=DeletionLedger(sqlite3.connect(':memory:'),key,initialize=True)
    backup=BackupStore(sqlite3.connect(':memory:'),key,initialize=True)
    paths={}
    for role in ROLES:
        paths[role]=tmp_path/(role+'.sqlite3')
        with sqlite3.connect(paths[role]) as db:
            if role=='cases':db.executescript("CREATE TABLE service_cases(id TEXT PRIMARY KEY,status TEXT,message TEXT,location TEXT,contact TEXT);INSERT INTO service_cases VALUES('c','new','PRIVATE-TEST','unit','phone');")
            elif role=='events':db.executescript("CREATE TABLE events(id TEXT PRIMARY KEY,zone TEXT,evidence TEXT,details_json TEXT);INSERT INTO events VALUES('e','PRIVATE-TEST','photo','{}');")
            elif role=='photos':db.executescript("CREATE TABLE cloud_photos(key TEXT PRIMARY KEY,event_id TEXT,content BLOB,digest TEXT);CREATE TABLE cloud_photo_tombstones(key TEXT PRIMARY KEY,event_id TEXT,erased_ms INTEGER);INSERT INTO cloud_photos VALUES('p','e',x'0102','hash');")
            elif role=='estate':db.executescript("CREATE TABLE cloud_operations(namespace TEXT,identity TEXT,payload TEXT);INSERT INTO cloud_operations VALUES('resident-case-photo-v1','c','PRIVATE-TEST');INSERT INTO cloud_operations VALUES('patrol-site','map','keep');")
            else:db.executescript("CREATE TABLE protected_data(value TEXT);INSERT INTO protected_data VALUES('MB842-counter-pause-audit');")
    identity='b'*32
    backup.publish(identity,paths,created_ms=1000,ledger_checkpoint=ledger.checkpoint(),source_fence_verified=True)
    old=backup.manifest(identity)
    ledger.append([{'kind':'case_purge','target':'c','revision':1,'erased_ms':2000},
                   {'kind':'event_purge','target':'e','revision':1,'erased_ms':2000}])
    assert backup.reconcile_erasure(identity,ledger=ledger,scratch_root=tmp_path,now_ms=2000,writer_fence=lambda:True)['reconciled']
    current=backup.manifest(identity)
    for role in ('usage','controls','memory','journal'):assert old['files'][role]==current['files'][role]
    assert current['ledger_checkpoint_at_backup']==ledger.checkpoint()
    restored=BackupStore(backup.db,key).download(identity,tmp_path/'download')
    for role,table in [('cases','service_cases'),('events','events'),('photos','cloud_photos')]:
        with sqlite3.connect(restored['files'][role]) as db:assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
    with sqlite3.connect(restored['files']['estate']) as db:assert db.execute('SELECT namespace FROM cloud_operations').fetchall()==[('patrol-site',)]
    assert not backup.reconcile_erasure(identity,ledger=ledger,scratch_root=tmp_path,now_ms=2001,writer_fence=lambda:True)['reconciled']
