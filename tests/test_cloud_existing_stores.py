import sqlite3
import threading
from contextlib import closing

import pytest
import test_cloud_bootstrap

from deploy.cloud.bootstrap import CloudStartupError, open_services
from edge_hub.assistant_memory import MemoryStore

prepared = test_cloud_bootstrap.prepared
seeded = test_cloud_bootstrap.seeded
KEY = test_cloud_bootstrap.KEY


def test_verified_cloud_assembly_never_runs_native_ddl_or_writes(seeded, monkeypatch):
    profile, _, _, _, _ = seeded
    original, statements, guard = profile.connect, [], threading.Lock()

    def connect(*args, **options):
        db = original(*args, **options)
        execute = db.execute

        def recorded(sql, *values):
            with guard:
                statements.append(sql)
            return execute(sql, *values)

        db.execute = recorded
        return db

    monkeypatch.setattr(profile, 'connect', connect)
    with open_services(profile, signing_key_loader=lambda: KEY, validation_workers=4) as services:
        assert services.events._stream_id
        assert services.memory.items()[0]['text'] == 'PUBLIC-SYNTHETIC-MEMORY'
    assert statements
    assert all(not sql.lstrip().split()[0].upper() in {'CREATE', 'ALTER', 'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}
               for sql in statements)
    assert not any('secure_delete' in sql or 'PRAGMA table_info(' in sql for sql in statements)


def test_existing_memory_missing_table_fails_without_initializing(tmp_path):
    path = tmp_path / 'public-empty.sqlite3'
    store = MemoryStore(path, connection_factory=sqlite3.connect, initialize=False)
    with pytest.raises(sqlite3.OperationalError):
        store.items()
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


def test_parallel_validation_failure_closes_readers_and_never_reaches_constructors(seeded, monkeypatch):
    profile, _, _, _, _ = seeded
    original, readers, keys = profile.connect, [], []
    with closing(original(test_cloud_bootstrap.path(profile, 'estate'))) as db, db:
        db.execute('DROP TABLE estate_knowledge')

    def connect(*args, **options):
        db = original(*args, **options)
        readers.append(db)
        return db

    monkeypatch.setattr(profile, 'connect', connect)
    with pytest.raises(CloudStartupError):
        open_services(profile, signing_key_loader=lambda: keys.append('requested'), validation_workers=4)
    assert not keys and readers
    for db in readers:
        with pytest.raises(sqlite3.Error):
            db.execute('SELECT 1')


@pytest.mark.parametrize('workers', [0, 5, True, 1.5])
def test_validation_pool_is_explicit_and_bounded(seeded, workers):
    profile, _, _, _, _ = seeded
    with pytest.raises(ValueError, match='explicit_cloud_startup_configuration_required'):
        open_services(profile, signing_key_loader=lambda: KEY, validation_workers=workers)
