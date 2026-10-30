import sqlite3

import pytest

from deploy.cloud.libsql_connection import Connection
from deploy.cloud.sql_import import ImportUncertain, fingerprint, import_database


@pytest.fixture(params=['sqlite', 'libsql'])
def target(request):
    if request.param == 'libsql':
        libsql = pytest.importorskip('libsql')
        db = Connection(libsql.connect(':memory:'), libsql.Error)
    else:
        db = sqlite3.connect(':memory:')
    yield db
    db.close()


@pytest.fixture
def source():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE cases(id INTEGER PRIMARY KEY AUTOINCREMENT,description TEXT,image BLOB,score REAL)')
    db.execute('CREATE INDEX case_text ON cases(description)')
    db.execute('INSERT INTO cases VALUES(8,?,?,?)', ('公開廣東話 MB842', b'\x00\xff', 3.25))
    db.execute('UPDATE sqlite_sequence SET seq=100')
    db.execute('CREATE TABLE usage(meter TEXT,period TEXT,amount INTEGER,PRIMARY KEY(meter,period)) WITHOUT ROWID')
    db.execute('INSERT INTO usage VALUES(?,?,?)', ('old-provider', '2026-09', 1987))
    db.execute('CREATE TABLE audit(message TEXT,at_ms INTEGER)')
    db.executemany('INSERT INTO audit(rowid,message,at_ms) VALUES(?,?,?)',
                   [(item * 2, '公開合成日誌', 1) for item in range(1, 2101)])
    db.execute('PRAGMA user_version=9')
    db.commit()
    yield db
    db.close()


def test_real_driver_bulk_import_keeps_schema_all_values_rowids_and_deleted_sequences(source, target):
    before = fingerprint(source)
    result = import_database(source, target)
    assert result['sha256'] == before['sha256'] and result['rows'] == 2102
    assert result['committed'] and not result['renumbered'] and not result['overwrote_existing_data']
    assert result['insert_statements'] < 12  # Not 2,102 separate remote requests.
    assert fingerprint(target) == before == fingerprint(source)
    assert target.execute('SELECT MAX(rowid) FROM audit').fetchone()[0] == 4200
    assert target.execute('INSERT INTO cases(description) VALUES(?)', ('公開新個案',)).lastrowid == 101


def test_nonempty_destination_never_overwritten_even_if_data_matches(source, target):
    import_database(source, target)
    before = fingerprint(target)
    with pytest.raises(ValueError, match='must_be_empty'):
        import_database(source, target)
    assert fingerprint(target) == before


def test_lost_commit_ack_requires_reconnect_comparison_not_resubmit(source):
    db = sqlite3.connect(':memory:')

    class LostCommit:
        def __getattr__(self, name):
            return getattr(db, name)

        def commit(self):
            db.commit()
            raise OSError('synthetic acknowledgement lost after real commit')

    with pytest.raises(ImportUncertain, match='reconnect_and_compare'):
        import_database(source, LostCommit())
    assert fingerprint(db) == fingerprint(source)
    with pytest.raises(ValueError, match='must_be_empty'):
        import_database(source, db)
    db.close()


def test_capacity_error_and_invalid_foreign_key_leave_target_empty(source, target):
    with pytest.raises(ValueError, match='capacity'):
        import_database(source, target, max_bytes=1024)
    assert target.execute('SELECT 1 FROM sqlite_master').fetchone() is None
    source.execute('CREATE TABLE child(id INTEGER REFERENCES cases(id))')
    source.execute('INSERT INTO child VALUES(555)')
    source.commit()
    with pytest.raises(ValueError, match='integrity_failed'):
        import_database(source, target)
    assert target.execute('SELECT 1 FROM sqlite_master').fetchone() is None


def test_triggers_are_rejected_instead_of_silently_skipped(source, target):
    source.execute('CREATE TRIGGER example AFTER INSERT ON cases BEGIN SELECT 1; END')
    source.commit()
    with pytest.raises(ValueError, match='unsupported_import_schema'):
        import_database(source, target)
    assert target.execute('SELECT 1 FROM sqlite_master').fetchone() is None


def test_readonly_header_metadata_avoids_redundant_setters_but_never_loses_nonzero_version(source):
    db = sqlite3.connect(':memory:')
    attempted = []

    class ReadonlyHeader:
        def __getattr__(self, name):
            return getattr(db, name)

        def execute(self, sql, parameters=()):
            if sql.startswith(('PRAGMA user_version=', 'PRAGMA application_id=')):
                attempted.append(sql)
                raise sqlite3.OperationalError('synthetic Turso read-only pragma')
            return db.execute(sql, parameters)

    # Reproduce the real remote failure without removing version verification.
    with pytest.raises(sqlite3.OperationalError, match='read-only pragma'):
        import_database(source, ReadonlyHeader())
    assert attempted == ['PRAGMA user_version=9']
    assert db.execute('SELECT 1 FROM sqlite_master').fetchone() is None
    source.execute('PRAGMA user_version=0')
    attempted.clear()
    result = import_database(source, ReadonlyHeader())
    assert result['committed'] and fingerprint(source) == fingerprint(db) and attempted == []
    db.close()


def test_large_photo_fingerprint_bounds_the_remote_sql_result_before_fetch():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE photos(id INTEGER PRIMARY KEY,content BLOB)')
    db.executemany('INSERT INTO photos VALUES(?,?)', [(i, b'PUBLIC-PHOTO-' * 3100) for i in range(80)])
    db.commit()
    sizes = []

    class BoundedHTTP:
        def __getattr__(self, name):
            return getattr(db, name)

        def execute(self, sql, parameters=()):
            cursor = db.execute(sql, parameters)
            if 'ORDER BY' in sql and 'FROM "photos"' in sql:
                rows = cursor.fetchall()
                size = sum(len(row[-1]) for row in rows)
                sizes.append(size)
                assert size <= 512 * 1024
                # Return a normal DB cursor after checking the actual response.
                return db.execute(sql, parameters)
            return cursor

    assert fingerprint(BoundedHTTP()) == fingerprint(db)
    assert len(sizes) > 3 and max(sizes) <= 512 * 1024
    db.close()
