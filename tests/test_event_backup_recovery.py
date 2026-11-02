import hashlib
import sqlite3

import pytest

from edge_hub.events import Event, EventStore
from tools.check_event_backup_recovery import check


@pytest.mark.parametrize('clear_first', [False, True])
def test_drill_restores_only_temporary_copy_and_preserves_source(tmp_path, clear_first):
    source = tmp_path / 'offline.sqlite3'
    store = EventStore(source)
    store.add(Event(id='fixture', type='robot_fault', zone='test', at_ms=5, severity='notice'))
    store.update_status('fixture', 'resolved')
    if clear_first:
        store.clear()
    store.close()
    raw = source.read_bytes()
    result = check(source, hashlib.sha256(raw).hexdigest())
    assert result['original_events'] == (0 if clear_first else 1)
    assert result['source_sha256_unchanged']
    assert result['clear_cursor_durable']
    assert result['production_database_restored'] is False
    assert result['complete_system_accepted'] is False
    assert source.read_bytes() == raw
    assert sorted(path.name for path in tmp_path.iterdir()) == ['offline.sqlite3']


def test_drill_refuses_wrong_hash_sidecars_or_wrong_schema(tmp_path):
    source = tmp_path / 'offline.sqlite3'
    store = EventStore(source)
    store.close()
    raw = source.read_bytes()
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        check(source, '0' * 64)
    sidecar = tmp_path / 'offline.sqlite3-wal'
    sidecar.write_bytes(b'not a standalone backup')
    with pytest.raises(ValueError, match='sidecars'):
        check(source, hashlib.sha256(raw).hexdigest())
    assert source.read_bytes() == raw
    missing = tmp_path / 'missing.sqlite3'
    with pytest.raises(ValueError, match='regular offline'):
        check(missing, '0' * 64)
    assert not missing.exists()
    other = tmp_path / 'wrong.sqlite3'
    with sqlite3.connect(other) as database:
        database.execute('CREATE TABLE unrelated (id INTEGER)')
    with pytest.raises(sqlite3.OperationalError):
        check(other, hashlib.sha256(other.read_bytes()).hexdigest())
