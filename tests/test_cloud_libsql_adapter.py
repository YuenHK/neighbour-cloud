"""Research driver only. Entirely in-memory, no Turso account/network required."""
import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

libsql = pytest.importorskip('libsql', reason='libSQL is isolated to the cloud research environment')
source = Path(__file__).resolve().parents[1] / 'deploy/cloud/libsql_connection.py'
spec = importlib.util.spec_from_file_location('cloud_libsql_adapter', source)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


@pytest.fixture
def db():
    connection = adapter.Connection(libsql.connect(':memory:'), libsql.Error)
    connection.execute('CREATE TABLE cases(id INTEGER PRIMARY KEY, message TEXT UNIQUE)')
    yield connection
    connection.close()


def test_named_rows_match_sqlite_index_keys_and_dict(db):
    db.row_factory = sqlite3.Row
    row = db.execute('SELECT 1 AS case_number, ? AS message', ('synthetic-case',)).fetchone()
    assert list(row) == [1, 'synthetic-case']
    assert row[0] == row['CASE_NUMBER'] == 1
    assert row[:] == (1, 'synthetic-case')
    assert dict(row) == {'case_number': 1, 'message': 'synthetic-case'}


def test_duplicate_column_lookup_matches_first_sqlite_column(db):
    db.row_factory = sqlite3.Row
    row = db.execute('SELECT 1 AS message, 2 AS MESSAGE').fetchone()
    assert row['message'] == row['MESSAGE'] == 1
    assert list(row) == [1, 2]


def test_context_rolls_back_all_issue_bindings_on_failure(db):
    with pytest.raises(ValueError), db:
        db.execute('INSERT INTO cases(message) VALUES (?)', ('synthetic-case',))
        assert db.in_transaction
        raise ValueError('isolated-failure')
    assert db.execute('SELECT COUNT(*) FROM cases').fetchone()[0] == 0
    assert not db.in_transaction


def test_short_case_numbers_and_changes_remain_atomic(db):
    with db:
        first = db.execute('INSERT INTO cases(message) VALUES (?)', ('one',)).lastrowid
        second = db.execute('INSERT INTO cases(message) VALUES (?)', ('two',)).lastrowid
    assert (first, second) == (1, 2)
    assert db.total_changes == 2
    assert db.execute('UPDATE cases SET message=? WHERE id=?', ('updated', first)).rowcount == 1
    db.rollback()
    assert db.execute('SELECT message FROM cases WHERE id=?', (first,)).fetchone()[0] == 'one'


def test_constraint_error_is_sqlite_compatible_without_private_text(db):
    with db:
        db.execute('INSERT INTO cases(message) VALUES (?)', ('PRIVATE-SYNTHETIC-VALUE',))
    with pytest.raises(sqlite3.IntegrityError) as caught, db:
        db.execute('INSERT INTO cases(message) VALUES (?)', ('PRIVATE-SYNTHETIC-VALUE',))
    assert 'PRIVATE-SYNTHETIC' not in str(caught.value)
    assert db.execute('SELECT COUNT(*) FROM cases').fetchone()[0] == 1


def test_unknown_sql_fails_without_swallowing_or_resetting_data(db):
    with db:
        db.execute('INSERT INTO cases(message) VALUES (?)', ('preserve',))
    with pytest.raises(sqlite3.OperationalError):
        db.execute('SELECT PRIVATE_INVALID_COLUMN FROM cases')
    assert db.execute('SELECT message FROM cases').fetchone()[0] == 'preserve'


def test_closed_connection_is_guarded_without_reentering_native_driver(db):
    cursor = db.execute('SELECT 1')
    db.close()
    db.close()  # The research driver must not be called again after disposal.
    for operation in (lambda: db.execute('SELECT 1'), lambda: db.executemany('SELECT 1', []),
                      lambda: db.executescript('SELECT 1'), db.commit, db.rollback,
                      db.__enter__, lambda: db.in_transaction, lambda: db.total_changes,
                      cursor.fetchone, cursor.fetchall, lambda: cursor.description,
                      lambda: cursor.lastrowid, lambda: cursor.rowcount):
        with pytest.raises(sqlite3.ProgrammingError):
            operation()


def use_driver(monkeypatch, module):
    def connect(database, **kwargs):
        raw = libsql.connect(str(database), timeout=kwargs.get('timeout', 5),
                             _check_same_thread=kwargs.get('check_same_thread', True))
        return adapter.Connection(raw, libsql.Error)
    shim = SimpleNamespace(**vars(sqlite3))
    shim.connect = connect
    monkeypatch.setattr(module, 'sqlite3', shim)


def test_real_case_store_keeps_numbers_reopen_and_staff_notes(tmp_path, monkeypatch):
    from edge_hub import service_desk

    use_driver(monkeypatch, service_desk)
    path = tmp_path / 'synthetic-cases.sqlite3'
    store = service_desk.ServiceDeskStore(path)
    request = service_desk.ResidentCase(submission_id='a' * 32, kind='water',
                                       message='公開合成漏水', confirmed=True)
    first = store.create(request)
    assert first['case_number'] == 1
    reviewed = store.review(first['id'], service_desk.ReviewCase(
        expected_revision=1, status='acknowledged', note='公開合成跟進'))
    assert reviewed['note'] == '公開合成跟進'
    store.close()
    store = service_desk.ServiceDeskStore(path)
    try:
        assert '公開合成跟進' in store.progress('1')
        assert store.progress('1') == store.progress('100001')
        assert store.create(request)['case_number'] == 1
        second = store.create(request.model_copy(update={'submission_id': 'b' * 32, 'message': '另一合成問題'}))
        assert second['case_number'] == 2
    finally:
        store.close()


def test_real_estate_store_invalidates_edited_answers(tmp_path, monkeypatch):
    from edge_hub import estate_services

    use_driver(monkeypatch, estate_services)
    store = estate_services.EstateStore(tmp_path / 'synthetic-estate.sqlite3')
    try:
        edit = estate_services.KnowledgeEdit(title='泳池', keywords=['泳池幾點'], answer='上午九點開放')
        store.save_knowledge('a' * 32, edit)
        assert store.knowledge()[0]['answer'] == '上午九點開放'
        store.prepare_index()
        store.save_knowledge('a' * 32, edit.model_copy(update={'answer': '上午十點開放', 'expected_revision': 1}))
        store.prepare_index()
        assert store._facts_rows[0]['answer'] == '上午十點開放'
    finally:
        store.close()


def test_real_memory_keeps_revision_and_only_explicit_records(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from edge_hub import assistant_memory

    use_driver(monkeypatch, assistant_memory)
    store = assistant_memory.MemoryStore(tmp_path / 'synthetic-memory.sqlite3')
    assert store.items() == []
    identity = store.remember('公開合成記憶')
    store.change(identity, 1, '公開合成更正')
    with pytest.raises(HTTPException) as caught:
        store.change(identity, 1, '過期修改')
    assert caught.value.status_code == 409
    assert store.items()[0]['text'] == '公開合成更正'
