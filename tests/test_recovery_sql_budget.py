import hashlib
import sqlite3
from types import SimpleNamespace

import pytest

from edge_hub.events import EventStore
from tools import check_event_backup_recovery as recovery

EXPENSIVE = ('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n '
             'WHERE x<1000000) SELECT sum(x) FROM n')


def source_fixture(tmp_path):
    source = tmp_path / 'offline.sqlite3'
    EventStore(source).close()
    return source, source.read_bytes()


def test_copied_integrity_query_observes_shared_sql_deadline(tmp_path, monkeypatch):
    source, raw = source_fixture(tmp_path)
    clock = [0.]
    monkeypatch.setattr(recovery.time, 'monotonic', lambda: clock[0])

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == 'PRAGMA quick_check':
                clock[0] = 31.
                super().execute(EXPENSIVE).fetchone()
                pytest.fail('expired SQL must be interrupted')
            return super().execute(sql, *args)

    connect = sqlite3.connect

    def connection(*args, **kwargs):
        return connect(*args, **kwargs, factory=Connection)

    monkeypatch.setattr(recovery, 'sqlite3', SimpleNamespace(connect=connection))
    with pytest.raises(sqlite3.OperationalError, match='interrupted') as error:
        recovery.check(source, hashlib.sha256(raw).hexdigest())
    assert error.value.sqlite_errorcode == sqlite3.SQLITE_INTERRUPT
    assert source.read_bytes() == raw


@pytest.mark.parametrize('stage', [0, 1, 2], ids=['migration-check', 'reopen-probe', 'reopen-empty'])
def test_every_reopened_store_installs_shared_sql_deadline(tmp_path, monkeypatch, stage):
    source, raw = source_fixture(tmp_path)
    clock, stores = [0.], []
    monkeypatch.setattr(recovery.time, 'monotonic', lambda: clock[0])

    class ConnectionProxy:
        def __init__(self, database, index):
            self.database, self.index = database, index

        def __getattr__(self, name):
            return getattr(self.database, name)

        def __enter__(self):
            return self.database.__enter__()

        def __exit__(self, *args):
            return self.database.__exit__(*args)

        def set_progress_handler(self, handler, instructions):
            self.database.set_progress_handler(handler, instructions)
            if self.index == stage:
                clock[0] = 31.
                self.database.execute(EXPENSIVE).fetchone()
                pytest.fail('expired store SQL must be interrupted')

    class Store(EventStore):
        def __init__(self, path):
            super().__init__(path)
            self._connection = ConnectionProxy(self._connection, len(stores))
            stores.append(self)

    monkeypatch.setattr(recovery, 'EventStore', Store)
    with pytest.raises(sqlite3.OperationalError, match='interrupted') as error:
        recovery.check(source, hashlib.sha256(raw).hexdigest())
    assert error.value.sqlite_errorcode == sqlite3.SQLITE_INTERRUPT
    assert len(stores) == stage + 1
    assert source.read_bytes() == raw
