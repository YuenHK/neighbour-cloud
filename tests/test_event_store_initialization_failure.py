import sqlite3

import pytest

from edge_hub.events import EventStore


@pytest.mark.parametrize('broken_schema', ['metadata', 'sequence', 'index'])
def test_failed_initialization_closes_connection_and_releases_locks(tmp_path, monkeypatch,
                                                                  broken_schema):
    database = tmp_path / 'broken.sqlite3'
    original_connect = sqlite3.connect
    initial = original_connect(database)
    if broken_schema == 'metadata':
        initial.execute('CREATE TABLE event_stream_metadata (bad TEXT)')
    elif broken_schema == 'sequence':
        initial.execute('CREATE TABLE event_ingest_sequence (bad TEXT)')
    else:
        initial.execute('CREATE TABLE events (id TEXT)')
        initial.execute("INSERT INTO events VALUES ('preserve-me')")
    initial.commit()
    initial.close()
    captured = []
    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        captured.append(connection)  # Keep alive: test must not rely on GC closing it.
        return connection
    monkeypatch.setattr('edge_hub.events.sqlite3.connect', connect)
    try:
        with pytest.raises(sqlite3.OperationalError):
            EventStore(database)
        assert len(captured) == 1
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            captured[0].execute('SELECT 1')
        other = original_connect(database, timeout=.01)
        try:
            other.execute('BEGIN IMMEDIATE')
            if broken_schema == 'index':
                assert other.execute('SELECT id FROM events').fetchall() == [('preserve-me',)]
                assert other.execute('SELECT COUNT(*) FROM event_ingest_sequence').fetchone()[0] == 0
            other.rollback()
        finally:
            other.close()
    finally:
        for connection in captured:
            connection.close()


def test_invalid_persisted_stream_identity_still_closes_without_regenerating(tmp_path, monkeypatch):
    database = tmp_path / 'invalid-identity.sqlite3'
    original_connect = sqlite3.connect
    initial = original_connect(database)
    initial.execute('CREATE TABLE event_stream_metadata (id INTEGER PRIMARY KEY,stream_id TEXT)')
    initial.execute("INSERT INTO event_stream_metadata VALUES (1,'invalid-keep')")
    initial.commit()
    initial.close()
    captured = []
    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        captured.append(connection)
        return connection
    monkeypatch.setattr('edge_hub.events.sqlite3.connect', connect)
    try:
        with pytest.raises(ValueError, match='do not regenerate'):
            EventStore(database)
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            captured[0].execute('SELECT 1')
        other = original_connect(database)
        try:
            assert other.execute('SELECT stream_id FROM event_stream_metadata').fetchone()[0] == 'invalid-keep'
        finally:
            other.close()
    finally:
        for connection in captured:
            connection.close()
