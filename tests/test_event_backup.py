import sqlite3

import pytest

from edge_hub.events import Event, EventStore
from tools.backup_events import backup


def test_live_sqlite_backup_preserves_events_and_refuses_overwrite(tmp_path):
    source, destination = tmp_path / 'live.sqlite3', tmp_path / 'backup.sqlite3'
    store = EventStore(source)
    store.add(Event(id='safe', type='robot_fault', zone='simulation', at_ms=1, severity='notice'))
    try:
        result = backup(source, destination)
        assert result['events'] == 1 and result['source_modified'] is False
        with sqlite3.connect(destination) as copied:
            assert copied.execute('SELECT id FROM events').fetchone()[0] == 'safe'
        with pytest.raises(FileExistsError):
            backup(source, destination)
        assert store.all()[0].id == 'safe'
    finally:
        store.close()


def test_backup_never_creates_a_missing_source(tmp_path):
    source = tmp_path / 'missing.sqlite3'
    with pytest.raises(ValueError):
        backup(source, tmp_path / 'backup.sqlite3')
    assert not source.exists()


def test_control_backup_preserves_safety_flags_without_creating_controller(tmp_path):
    from edge_hub.robot_control import RobotController

    source, destination = tmp_path / 'control.sqlite3', tmp_path / 'backup.sqlite3'
    controller = RobotController(source)
    controller.software_stop()
    try:
        result = backup(source, destination, kind='robot-control')
        assert result['control_audit'] == 1
        assert result['safety_marker'] == {'requires_reset': True, 'fault': False}
        assert result['kind'] == 'robot-control'
        with sqlite3.connect(destination) as copied:
            assert copied.execute('SELECT requires_reset FROM control_safety').fetchone()[0] == 1
        assert controller.status()['software_stop_latched']
        with pytest.raises(FileExistsError):
            backup(source, destination, kind='robot-control')
    finally:
        controller.close()


def test_control_backup_accepts_legacy_schema_but_does_not_invent_safety_state(tmp_path):
    source, destination = tmp_path / 'legacy.sqlite3', tmp_path / 'backup.sqlite3'
    with sqlite3.connect(source) as database:
        database.execute('CREATE TABLE control_audit '
                         '(id INTEGER PRIMARY KEY,at_ms INTEGER,action TEXT,reason TEXT)')
    result = backup(source, destination, kind='robot-control')
    assert result['safety_marker'] is None
    with sqlite3.connect(source) as original:
        assert original.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='control_safety'").fetchone()[0] == 0


def test_wrong_database_kind_rejected_before_creating_destination(tmp_path):
    source, destination = tmp_path / 'events.sqlite3', tmp_path / 'backup.sqlite3'
    store = EventStore(source)
    try:
        with pytest.raises(ValueError, match='schema'):
            backup(source, destination, kind='robot-control')
        assert not destination.exists()
    finally:
        store.close()


@pytest.mark.parametrize('timeout', [0, -1, float('inf'), float('nan'), 61])
def test_invalid_backup_time_budget_rejected_before_any_file_creation(tmp_path, timeout):
    with pytest.raises(ValueError, match='timeout'):
        backup(tmp_path / 'missing.sqlite3', tmp_path / 'out.sqlite3', timeout=timeout)
    assert not (tmp_path / 'out.sqlite3').exists()


def test_wal_control_backup_includes_committed_audit_and_safety_snapshot(tmp_path):
    source, destination = tmp_path / 'live.sqlite3', tmp_path / 'snapshot.sqlite3'
    with sqlite3.connect(source) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE control_audit (id INTEGER,at_ms INTEGER,action TEXT,reason TEXT)')
        writer.execute('CREATE TABLE control_safety (id INTEGER,requires_reset INTEGER,fault INTEGER)')
        writer.execute("INSERT INTO control_audit VALUES (1,1,'stop','test')")
        writer.execute('INSERT INTO control_safety VALUES (1,1,1)')
        writer.commit()
        result = backup(source, destination, kind='robot-control')
        assert result['control_audit'] == 1
        assert result['safety_marker'] == {'requires_reset': True, 'fault': True}


def test_invalid_safety_marker_is_not_reported_as_verified_backup(tmp_path):
    source, destination = tmp_path / 'bad.sqlite3', tmp_path / 'snapshot.sqlite3'
    with sqlite3.connect(source) as database:
        database.execute('CREATE TABLE control_audit (id INTEGER,at_ms INTEGER,action TEXT,reason TEXT)')
        database.execute('CREATE TABLE control_safety (id INTEGER,requires_reset INTEGER,fault INTEGER)')
        database.execute('INSERT INTO control_safety VALUES (1,7,0)')
    with pytest.raises(ValueError, match='safety'):
        backup(source, destination, kind='robot-control')
    assert not destination.exists()


def test_copy_timeout_keeps_partial_output_but_never_claims_success(tmp_path, monkeypatch):
    import tools.backup_events as module

    source, destination = tmp_path / 'legacy.sqlite3', tmp_path / 'partial.sqlite3'
    with sqlite3.connect(source) as database:
        database.execute('CREATE TABLE control_audit (id INTEGER,at_ms INTEGER,action TEXT,reason TEXT)')
    ticks = iter([0., 0., 31.])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(TimeoutError, match='not a verified backup'):
        backup(source, destination, kind='robot-control')
    assert source.exists() and destination.exists()


def test_backup_hash_does_not_load_entire_database_into_memory(tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path

    source, destination = tmp_path / 'live.sqlite3', tmp_path / 'backup.sqlite3'
    store = EventStore(source)
    try:
        store.add(Event(id='safe', type='robot_fault', zone='fixture', at_ms=1, severity='notice'))
        def forbidden(*args, **kwargs):
            raise AssertionError('whole-file read_bytes is not a bounded checksum')
        monkeypatch.setattr(Path, 'read_bytes', forbidden)
        report = backup(source, destination)
        with destination.open('rb') as copied:
            assert report['sha256'] == hashlib.file_digest(copied, 'sha256').hexdigest()
        assert report['quick_check'] == 'ok'
    finally:
        store.close()


def test_chunked_backup_hash_checks_budget_between_chunks_and_at_eof(tmp_path):
    import hashlib

    from tools.backup_events import backup_sha256

    path = tmp_path / 'data'
    raw = b'payload' * 400_000
    path.write_bytes(raw)
    calls = []
    assert backup_sha256(path, lambda: calls.append(True)) == hashlib.sha256(raw).hexdigest()
    assert len(calls) >= 4  # multi-chunk input, including deadline check after EOF


def test_checksum_timeout_never_returns_a_verified_hash_or_deletes_output(tmp_path):
    from tools.backup_events import backup_sha256

    path = tmp_path / 'partial.sqlite3'
    path.write_bytes(b'x' * (2 * 1024 * 1024))
    calls = 0
    def progress():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError('checksum deadline')
    with pytest.raises(TimeoutError, match='checksum deadline'):
        backup_sha256(path, progress)
    assert calls == 2 and path.stat().st_size == 2 * 1024 * 1024


def test_backup_timeout_in_checksum_phase_preserves_files_without_success(tmp_path, monkeypatch):
    import tools.backup_events as module

    source, destination = tmp_path / 'source.sqlite3', tmp_path / 'unverified.sqlite3'
    store = EventStore(source)
    original_hash = module.backup_sha256
    def checksum(path, progress):
        monkeypatch.setattr(module.time, 'monotonic', lambda: 1e20)
        return original_hash(path, progress)
    try:
        store.add(Event(id='safe', type='robot_fault', zone='fixture', at_ms=1, severity='notice'))
        monkeypatch.setattr(module, 'backup_sha256', checksum)
        with pytest.raises(TimeoutError, match='not a verified backup'):
            backup(source, destination)
        assert destination.is_file() and destination.stat().st_size > 0
        assert store.all()[0].id == 'safe'
    finally:
        store.close()
