import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import check_control_backup_recovery as recovery


def source_database(path, kind='clean'):
    with closing(sqlite3.connect(path)) as database, database:
        database.execute('CREATE TABLE control_audit (id INTEGER PRIMARY KEY,at_ms INTEGER,action TEXT,reason TEXT)')
        if kind != 'legacy-empty':
            database.execute("INSERT INTO control_audit VALUES (7,100,'stop','historical')")
        if not kind.startswith('legacy'):
            database.execute('CREATE TABLE control_safety (id INTEGER PRIMARY KEY,requires_reset INTEGER,fault INTEGER)')
            database.execute('INSERT INTO control_safety VALUES (1,?,?)',
                             (int(kind == 'latched' or kind == 'fault'), int(kind == 'fault')))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('kind,state', [('clean', 'idle'), ('latched', 'safe_stop'), ('fault', 'fault'),
                                       ('legacy-history', 'safe_stop'), ('legacy-empty', 'idle')])
def test_disposable_control_restore_preserves_source_and_safety(tmp_path, monkeypatch, kind, state):
    source = tmp_path / 'offline.sqlite3'
    checksum = source_database(source, kind)
    raw = source.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail('control recovery must not start worker or drive')

    monkeypatch.setattr(recovery.RobotController, 'start', forbidden)
    monkeypatch.setattr(recovery.SimulatedTransport, 'drive', forbidden)
    report = recovery.check(source, checksum)
    assert report['passed'] and report['audit_identity_preserved']
    assert report['initial_state'] == state
    assert report['initial_state_without_lease_or_motion']
    assert report['existing_safety_marker_preserved'] is (None if kind.startswith('legacy') else True)
    assert report['fault_reset_denial_verified'] is (True if kind == 'fault' else None)
    assert report['source_sha256_unchanged']
    assert report['production_database_restored'] is report['hardware_acceptance'] is False
    assert source.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_control_drill_refuses_sidecars(tmp_path, suffix):
    source = tmp_path / 'offline.sqlite3'
    checksum = source_database(source)
    Path(str(source) + suffix).write_bytes(b'sidecar')
    with pytest.raises(ValueError, match='sidecars'):
        recovery.check(source, checksum)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == checksum


def test_control_drill_refuses_wrong_hash_or_schema(tmp_path):
    source = tmp_path / 'offline.sqlite3'
    checksum = source_database(source)
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        recovery.check(source, '0' * 64)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == checksum
    wrong = tmp_path / 'wrong.sqlite3'
    with closing(sqlite3.connect(wrong)) as database, database:
        database.execute('CREATE TABLE unrelated (id INTEGER)')
    with pytest.raises(ValueError, match='schema'):
        recovery.check(wrong, hashlib.sha256(wrong.read_bytes()).hexdigest())


def test_control_drill_enforces_audit_budget(tmp_path, monkeypatch):
    source = tmp_path / 'offline.sqlite3'
    checksum = source_database(source)
    monkeypatch.setattr(recovery, 'MAX_AUDIT_ROWS', 0)
    with pytest.raises(ValueError, match='row budget'):
        recovery.check(source, checksum)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == checksum


def test_existing_report_is_preserved_before_recovery(tmp_path, monkeypatch):
    report = tmp_path / 'report.json'
    report.write_text('previous evidence', encoding='utf-8')

    def forbidden(*args):
        pytest.fail('existing report must be refused before recovery')

    monkeypatch.setattr(recovery, 'check', forbidden)
    monkeypatch.setattr(sys, 'argv', ['recovery', '--source', 'not-opened.sqlite3', '--sha256', '0' * 64,
                                    '--report', str(report)])
    with pytest.raises(FileExistsError, match='preserve'):
        recovery.main()
    assert report.read_text(encoding='utf-8') == 'previous evidence'


@pytest.mark.parametrize('kind', ['audit', 'safety'])
def test_corrupted_disposable_copy_cannot_report_success(tmp_path, monkeypatch, kind):
    source = tmp_path / 'offline.sqlite3'
    checksum = source_database(source, 'fault')
    original_controller = recovery.RobotController

    def corrupt_copy(path, **kwargs):
        with closing(sqlite3.connect(path)) as database, database:
            if kind == 'audit':
                database.execute("UPDATE control_audit SET reason='changed'")
            else:
                database.execute('UPDATE control_safety SET requires_reset=0,fault=0')
        return original_controller(path, **kwargs)

    monkeypatch.setattr(recovery, 'RobotController', corrupt_copy)
    with pytest.raises(RuntimeError, match='changed'):
        recovery.check(source, checksum)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == checksum


def test_expired_initial_hash_budget_cannot_create_recovery_directory(tmp_path, monkeypatch):
    source = tmp_path / 'offline.sqlite3'
    checksum = source_database(source)
    ticks = iter([0., 31.])
    monkeypatch.setattr(recovery, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))

    def forbidden(**kwargs):
        pytest.fail('expired hash budget must fail before temporary restore')

    monkeypatch.setattr(recovery, 'tempfile', SimpleNamespace(TemporaryDirectory=forbidden))
    with pytest.raises(TimeoutError, match='deadline'):
        recovery.check(source, checksum)


def test_cli_creates_new_report_for_temporary_backup_only(tmp_path, monkeypatch, capsys):
    source = tmp_path / 'offline.sqlite3'
    checksum = source_database(source, 'fault')
    output = tmp_path / 'new-report.json'
    monkeypatch.setattr(sys, 'argv', ['recovery', '--source', str(source), '--sha256', checksum,
                                    '--report', str(output)])
    assert recovery.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert json.loads(output.read_text(encoding='utf-8')) == report
    assert report['fault_reset_denial_verified'] is True
    assert report['production_database_restored'] is False
    assert hashlib.sha256(source.read_bytes()).hexdigest() == checksum
