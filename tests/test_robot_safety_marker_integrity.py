import sqlite3
from contextlib import closing

import pytest

from edge_hub.robot_control import ControlError, RobotController


def fixture_db(path, rows=None):
    with closing(sqlite3.connect(path)) as database, database:
        database.execute('CREATE TABLE control_audit (id INTEGER PRIMARY KEY,at_ms INTEGER,action TEXT,reason TEXT)')
        if rows is not None:
            database.execute('CREATE TABLE control_safety (id,requires_reset,fault)')
            database.executemany('INSERT INTO control_safety VALUES (?,?,?)', rows)


@pytest.mark.parametrize('rows', [[], [(2, 0, 0)], [(1, 0, 0), (1, 1, 1)],
                                  [(1, '0', 0)], [(1, None, 0)], [(1, 2, 0)],
                                  [(1, 0., 0)], [(1, 0, 'private-invalid')]],
                         ids=['empty', 'wrong-id', 'duplicate', 'text', 'null', 'range', 'float', 'private'])
def test_invalid_existing_marker_refuses_start_without_repair_and_closes_db(tmp_path, monkeypatch, rows):
    source = tmp_path / 'control.sqlite3'
    fixture_db(source, rows)
    original_connect = sqlite3.connect
    connections = []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr('edge_hub.robot_control.sqlite3.connect', connect)
    with pytest.raises(ControlError, match='^control_safety_storage_invalid$') as error:
        RobotController(source)
    assert error.value.status == 503
    with pytest.raises(sqlite3.ProgrammingError):
        connections[0].execute('SELECT 1')
    with closing(original_connect(source)) as database:
        assert database.execute('SELECT * FROM control_safety').fetchall() == rows
        assert database.execute('SELECT COUNT(*) FROM control_audit').fetchone()[0] == 0


def test_safety_view_is_not_a_persistent_marker(tmp_path):
    source = tmp_path / 'control.sqlite3'
    fixture_db(source)
    with closing(sqlite3.connect(source)) as database, database:
        database.execute('CREATE VIEW control_safety AS SELECT 1 AS id,0 AS requires_reset,0 AS fault')
    with pytest.raises(ControlError, match='^control_safety_storage_invalid$'):
        RobotController(source)


@pytest.mark.parametrize('flags', [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_valid_integer_marker_retains_restart_semantics(tmp_path, flags):
    source = tmp_path / 'control.sqlite3'
    fixture_db(source, [(1, *flags)])
    controller = RobotController(source)
    try:
        assert controller.state == ('fault' if flags[1] else 'safe_stop' if flags[0] else 'idle')
        assert controller.stop_latched is bool(any(flags))
        assert controller.direction == 'stop' and controller.lease is None
        assert controller.audit() == []
    finally:
        controller.close()


@pytest.mark.parametrize('history', [False, True])
def test_genuinely_absent_legacy_table_still_migrates_conservatively(tmp_path, history):
    source = tmp_path / 'control.sqlite3'
    fixture_db(source)
    if history:
        with closing(sqlite3.connect(source)) as database, database:
            database.execute("INSERT INTO control_audit VALUES (1,1,'stop','legacy')")
    controller = RobotController(source)
    try:
        assert controller.stop_latched is history
        assert controller.direction == 'stop' and controller.lease is None
    finally:
        controller.close()


@pytest.mark.parametrize('failure', ['deleted', 'ignored-update', 'rewritten-flags'])
def test_audit_cannot_acknowledge_missing_or_unpreserved_marker(failure):
    controller = RobotController()
    try:
        if failure == 'deleted':
            controller.db.execute('DELETE FROM control_safety')
        elif failure == 'ignored-update':
            controller.db.execute('CREATE TRIGGER reject_flags BEFORE UPDATE ON control_safety '
                                  'BEGIN SELECT RAISE(IGNORE); END')
        else:
            controller.db.execute('CREATE TRIGGER rewrite_flags AFTER UPDATE ON control_safety '
                                  'BEGIN UPDATE control_safety SET requires_reset=0,fault=0 WHERE id=1; END')
        controller.db.commit()
        with pytest.raises(ControlError, match='^control_audit_unavailable$') as error:
            controller.acquire()
        assert error.value.status == 503
        assert controller.state == 'fault' and controller.stop_latched
        assert controller.lease is None and controller.direction == 'stop'
        assert controller.transport.direction == 'stop' and controller.stopping.is_set()
        assert controller.audit() == []  # Attempted acquisition audit was rolled back.
        if failure != 'deleted':
            assert controller.db.execute('SELECT fault FROM control_safety').fetchone()[0] == 0
        with pytest.raises(ControlError, match='^transport_fault_requires_on_site_check$'):
            controller.reset_software_stop()
    finally:
        # Deliberately broken memory storage cannot acknowledge normal close;
        # no worker or hardware exists in this fixture.
        controller.db.close()
