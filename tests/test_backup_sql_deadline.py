import hashlib
import sqlite3

import pytest

from tools import backup_events


@pytest.mark.parametrize('stage', ['source', 'copy'])
def test_expensive_inspection_interrupts_at_deadline_without_claiming_backup(tmp_path, monkeypatch, stage):
    source, destination = tmp_path / 'source.sqlite3', tmp_path / 'partial.sqlite3'
    with sqlite3.connect(source) as database:
        database.execute('CREATE TABLE control_audit (id INTEGER,at_ms INTEGER,action TEXT,reason TEXT)')
        database.execute("INSERT INTO control_audit VALUES (1,1,'stop','fixture')")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    clock, calls = [0.], []
    monkeypatch.setattr(backup_events.time, 'monotonic', lambda: clock[0])
    real_inspect = backup_events.inspect_database

    def inspect(database, kind):
        calls.append(True)
        if len(calls) == (1 if stage == 'source' else 2):
            clock[0] = 31.
            # Query execution, not Python callbacks, must observe the SQL handler.
            database.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL '
                             'SELECT x+1 FROM n WHERE x<1000000) SELECT sum(x) FROM n').fetchone()
            pytest.fail('expired SQL must not complete')
        return real_inspect(database, kind)

    monkeypatch.setattr(backup_events, 'inspect_database', inspect)
    with pytest.raises(sqlite3.OperationalError, match='interrupted') as error:
        backup_events.backup(source, destination, kind='robot-control')
    assert error.value.sqlite_errorcode == sqlite3.SQLITE_INTERRUPT
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert destination.exists() is (stage == 'copy')  # Partial output is retained, never verified.
    if destination.exists():
        with pytest.raises(FileExistsError):
            clock[0] = 0.
            monkeypatch.setattr(backup_events, 'inspect_database', real_inspect)
            backup_events.backup(source, destination, kind='robot-control')


def test_sql_interruption_is_not_silenced_or_relabelled_as_verified(tmp_path, monkeypatch):
    source = tmp_path / 'source.sqlite3'
    with sqlite3.connect(source) as database:
        database.execute('CREATE TABLE events (id,type,zone,at_ms,severity)')

    def interrupted(database, kind):
        raise sqlite3.OperationalError('interrupted')

    monkeypatch.setattr(backup_events, 'inspect_database', interrupted)
    with pytest.raises(sqlite3.OperationalError, match='interrupted'):
        backup_events.backup(source, tmp_path / 'out.sqlite3')
    assert not (tmp_path / 'out.sqlite3').exists()
