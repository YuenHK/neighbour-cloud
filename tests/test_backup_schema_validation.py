import hashlib
import sqlite3

import pytest

from tools.backup_events import backup


def create_control(path, rows):
    with sqlite3.connect(path) as database:
        database.execute('CREATE TABLE control_audit (id,at_ms,action,reason)')
        database.execute('CREATE TABLE control_safety (id,requires_reset,fault)')
        database.executemany('INSERT INTO control_safety VALUES (?,?,?)', rows)


@pytest.mark.parametrize('row', [
    (1., 0, 1), (1, 0., 1), (1, 0, 1.), (1, '0', 1), (1, 0, b'1'),
    (1, None, 1), (2, 0, 1), (1, -1, 0), (1, 0, 2),
])
def test_invalid_marker_storage_or_values_rejected_without_output(tmp_path, row):
    source, destination = tmp_path / 'source.sqlite3', tmp_path / 'out.sqlite3'
    create_control(source, [row])
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='safety'):
        backup(source, destination, kind='robot-control')
    assert not destination.exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


@pytest.mark.parametrize('rows', [[], [(1, 0, 0), (1, 0, 0)]])
def test_empty_or_duplicate_marker_rejected(tmp_path, rows):
    source, destination = tmp_path / 'source.sqlite3', tmp_path / 'out.sqlite3'
    create_control(source, rows)
    with pytest.raises(ValueError, match='safety'):
        backup(source, destination, kind='robot-control')
    assert not destination.exists()


@pytest.mark.parametrize('requires_reset,fault', [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_integer_flags_preserved_without_inventing_hardware_safety(tmp_path, requires_reset, fault):
    source, destination = tmp_path / 'source.sqlite3', tmp_path / 'out.sqlite3'
    create_control(source, [(1, requires_reset, fault)])
    report = backup(source, destination, kind='robot-control')
    assert report['safety_marker'] == {'requires_reset': bool(requires_reset), 'fault': bool(fault)}
    assert report['source_modified'] is False


@pytest.mark.parametrize('kind,table,projection', [
    ('events', 'events', '1 AS id,1 AS type,1 AS zone,1 AS at_ms,1 AS severity'),
    ('robot-control', 'control_audit', '1 AS id,1 AS at_ms,1 AS action,1 AS reason'),
    ('robot-control', 'control_safety', '1 AS id,0 AS requires_reset,0 AS fault'),
])
def test_view_cannot_impersonate_required_table(tmp_path, kind, table, projection):
    source, destination = tmp_path / 'source.sqlite3', tmp_path / 'out.sqlite3'
    with sqlite3.connect(source) as database:
        if table == 'control_safety':
            database.execute('CREATE TABLE control_audit (id,at_ms,action,reason)')
        database.execute(f'CREATE VIEW {table} AS SELECT {projection}')
    with pytest.raises(ValueError, match='schema'):
        backup(source, destination, kind=kind)
    assert not destination.exists()
