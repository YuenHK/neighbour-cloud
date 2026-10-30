import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'deploy/cloud'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshots = load('sql_snapshot')


@pytest.fixture(params=['sqlite', 'libsql'])
def source(request):
    if request.param == 'libsql':
        driver = pytest.importorskip('libsql')
        adapter = load('libsql_connection')
        db = adapter.Connection(driver.connect(':memory:'), driver.Error)
    else:
        db = sqlite3.connect(':memory:')
    yield db
    db.close()


def populate(db):
    db.execute('CREATE TABLE cases(id INTEGER PRIMARY KEY AUTOINCREMENT, description TEXT, image BLOB)')
    db.execute('CREATE INDEX descriptions ON cases(description)')
    db.execute('INSERT INTO cases(description,image) VALUES(?,?)', ('公開合成測試', b'\0\xff\x01'))
    db.execute('INSERT INTO cases(description) VALUES(?)', ('removed-synthetic',))
    db.execute('DELETE FROM cases WHERE id=2')
    db.execute('CREATE TABLE usage(meter TEXT PRIMARY KEY, amount INTEGER NOT NULL) WITHOUT ROWID')
    db.execute('INSERT INTO usage VALUES(?,?)', ('synthetic-quota', 612))
    db.commit()


def test_snapshot_restores_blobs_unicode_indexes_counters_and_next_number(source, tmp_path):
    populate(source)
    result = snapshots.snapshot(source, tmp_path / 'new.sqlite3')
    assert result['tables'] == 2 and result['rows'] == 2
    assert result['consistent_read_transaction'] and result['integrity_verified']
    assert not source.in_transaction
    with sqlite3.connect(tmp_path / 'new.sqlite3') as restored:
        assert restored.execute('SELECT * FROM cases').fetchone() == (1, '公開合成測試', b'\0\xff\x01')
        assert restored.execute('SELECT amount FROM usage').fetchone()[0] == 612
        assert restored.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='descriptions'").fetchone()
        assert restored.execute('INSERT INTO cases(description) VALUES(?)', ('next',)).lastrowid == 3


def test_snapshot_refuses_existing_target_and_active_source_transaction(source, tmp_path):
    populate(source)
    original = tmp_path / 'existing'
    original.write_bytes(b'preserve-existing')
    with pytest.raises(ValueError, match='must_be_new'):
        snapshots.snapshot(source, original)
    assert original.read_bytes() == b'preserve-existing'
    source.execute('BEGIN')
    with pytest.raises(ValueError, match='idle_dedicated'):
        snapshots.snapshot(source, tmp_path / 'new')
    assert source.in_transaction and not (tmp_path / 'new').exists()
    source.rollback()


def test_snapshot_never_silently_omits_a_trigger(source, tmp_path):
    populate(source)
    source.execute('CREATE TRIGGER example AFTER INSERT ON cases BEGIN SELECT 1; END')
    source.commit()
    with pytest.raises(ValueError, match='unsupported_snapshot_schema'):
        snapshots.snapshot(source, tmp_path / 'new')
    assert not (tmp_path / 'new').exists()
    assert not source.in_transaction


def test_snapshot_capacity_and_deadline_are_failures_not_completions(source, tmp_path):
    populate(source)
    with pytest.raises(ValueError, match='snapshot_capacity'):
        snapshots.snapshot(source, tmp_path / 'small', max_bytes=1024)
    times = iter([0, 1, 2, 10, 11, 12, 13])
    with pytest.raises(ValueError, match='snapshot_deadline'):
        snapshots.snapshot(source, tmp_path / 'late', timeout=3, clock=lambda: next(times))
    assert not source.in_transaction
    assert source.execute('SELECT amount FROM usage').fetchone()[0] == 612


def test_snapshot_multiple_bounded_pages_preserve_all_rows(source, tmp_path):
    source.execute('CREATE TABLE facts(id INTEGER PRIMARY KEY, description TEXT)')
    source.executemany('INSERT INTO facts VALUES(?,?)', [(index, 'synthetic') for index in range(311)])
    source.commit()
    assert snapshots.snapshot(source, tmp_path / 'new')['rows'] == 311
    with sqlite3.connect(tmp_path / 'new') as restored:
        assert restored.execute('SELECT COUNT(*),SUM(id) FROM facts').fetchone() == (311, sum(range(311)))


def test_large_rowid_backup_uses_indexed_continuation_without_rescanning_prior_pages(source, tmp_path):
    source.execute('CREATE TABLE records(_rowid_ TEXT,rowid TEXT,payload BLOB)')
    rows = [(index * 31 - 21000, 'PUBLIC-'+str(index), 'row-'+str(index), b'PUBLIC-SYNTHETIC') for index in range(1300)]
    source.executemany('INSERT INTO records(oid,_rowid_,rowid,payload) VALUES(?,?,?,?)', rows)
    source.commit()
    calls = []

    class NoOffsetScan:
        def __getattr__(self, name):
            return getattr(source, name)

        def execute(self, sql, parameters=()):
            if sql.startswith('SELECT ') and ('FROM "records" ORDER BY' in sql or 'FROM "records" WHERE' in sql):
                assert 'OFFSET' not in sql
                calls.append((sql, parameters))
            return source.execute(sql, parameters)

    result = snapshots.snapshot(NoOffsetScan(), tmp_path/'continued.sqlite3')
    assert result['rows'] == len(rows) and len(calls) >= 3
    assert any('WHERE "oid"> ?' in sql for sql, _ in calls[1:])
    with sqlite3.connect(tmp_path/'continued.sqlite3') as restored:
        assert restored.execute('SELECT oid,_rowid_,rowid,payload FROM records ORDER BY oid').fetchall() == rows


def test_without_rowid_collation_ties_never_skip_rows(source, tmp_path):
    source.execute('CREATE TABLE names(name TEXT COLLATE NOCASE,version INTEGER, '
                   'PRIMARY KEY(name COLLATE BINARY,version)) WITHOUT ROWID')
    rows = [(str(index)+'a',1) for index in range(600)]+[(str(index)+'A',1) for index in range(600)]
    source.executemany('INSERT INTO names VALUES(?,?)', rows)
    source.commit()
    assert snapshots.snapshot(source,tmp_path/'names.sqlite3')['rows'] == len(rows)
    with sqlite3.connect(tmp_path/'names.sqlite3') as restored:
        assert set(restored.execute('SELECT * FROM names')) == set(rows)


def test_snapshot_rejects_missing_foreign_reference(source, tmp_path):
    source.execute('PRAGMA foreign_keys=OFF')
    source.execute('CREATE TABLE parent(id INTEGER PRIMARY KEY)')
    source.execute('CREATE TABLE child(id INTEGER PRIMARY KEY REFERENCES parent(id))')
    source.execute('INSERT INTO child VALUES (1)')
    source.commit()
    with pytest.raises(ValueError, match='foreign_key_check_failed'):
        snapshots.snapshot(source, tmp_path / 'new')
    assert not source.in_transaction


def test_snapshot_preserves_implicit_rowids_for_same_millisecond_issue_order(source, tmp_path):
    source.execute('CREATE TABLE notes(id TEXT PRIMARY KEY, content TEXT)')
    source.execute('INSERT INTO notes(rowid,id,content) VALUES(?,?,?)', (8, 'b', 'first'))
    source.execute('INSERT INTO notes(rowid,id,content) VALUES(?,?,?)', (19, 'a', 'last'))
    source.execute('PRAGMA user_version=7')
    source.commit()
    snapshots.snapshot(source, tmp_path / 'new')
    with sqlite3.connect(tmp_path / 'new') as restored:
        assert restored.execute('SELECT rowid,id FROM notes ORDER BY rowid').fetchall() == [(8, 'b'), (19, 'a')]
        assert restored.execute('PRAGMA user_version').fetchone()[0] == 7


def test_actual_workbench_schema_recovers_short_numbers_notes_and_original_rows(source, tmp_path, monkeypatch):
    from edge_hub import service_desk

    with monkeypatch.context() as patch:
        shim = SimpleNamespace(**vars(sqlite3))
        shim.connect = lambda *args, **kwargs: source
        patch.setattr(service_desk, 'sqlite3', shim)
        store = service_desk.ServiceDeskStore(tmp_path / 'synthetic-source')
        first = store.create(service_desk.ResidentCase(submission_id='a' * 32, kind='water',
                             message='公開合成漏水', confirmed=True))
        store.review(first['id'], service_desk.ReviewCase(status='acknowledged', expected_revision=1,
                                                        note='公開合成職員跟進'))
        prior = [tuple(row) for row in source.execute('SELECT rowid,* FROM service_cases ORDER BY rowid')]
        snapshots.snapshot(source, tmp_path / 'recovered.sqlite3')
    recovered = service_desk.ServiceDeskStore(tmp_path / 'recovered.sqlite3')
    try:
        assert [tuple(row) for row in recovered.db.execute('SELECT rowid,* FROM service_cases ORDER BY rowid')] == prior
        assert '公開合成職員跟進' in recovered.progress('1')
        assert recovered.progress('1') == recovered.progress('100001')
        next_case = recovered.create(service_desk.ResidentCase(submission_id='b' * 32, kind='litter',
                                        message='另一合成問題', confirmed=True))
        assert next_case['case_number'] == 2
    finally:
        recovered.close()
