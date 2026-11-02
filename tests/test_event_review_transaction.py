import sqlite3

import pytest

from edge_hub.events import Event, EventStore


def event(identifier):
    return Event(id=identifier, type='litter_detected', zone='fixture', at_ms=1,
                 severity='notice')


def test_review_commit_busy_rolls_back_before_later_successful_write(tmp_path):
    database = tmp_path / 'events.sqlite3'
    store = EventStore(database)
    reader = sqlite3.connect(database)
    try:
        store.add(event('original'))
        store._connection.execute('PRAGMA busy_timeout=1')
        reader.execute('BEGIN')
        reader.execute('SELECT * FROM events').fetchall()
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                store.update_status('original', 'confirmed')
            assert store._connection.in_transaction is False
            assert store.query()[0].status == 'pending'
        finally:
            reader.rollback()
        store.add(event('later'))
    finally:
        reader.close()
        store.close()
    reopened = EventStore(database)
    try:
        assert {row.id: row.status for row in reopened.all()} == {
            'original': 'pending', 'later': 'pending'}
        assert reopened.update_status('original', 'resolved').status == 'resolved'
    finally:
        reopened.close()


def test_review_statement_failure_does_not_leave_transaction_open():
    store = EventStore()
    try:
        store.add(event('original'))
        store._connection.execute("CREATE TRIGGER reject_review BEFORE UPDATE ON events "
                                  "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        store._connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match='synthetic failure'):
            store.update_status('original', 'confirmed')
        assert store._connection.in_transaction is False
        assert store.query()[0].status == 'pending'
        store._connection.execute('DROP TRIGGER reject_review')
        store._connection.commit()
        assert store.update_status('original', 'resolved').status == 'resolved'
    finally:
        store.close()


@pytest.mark.parametrize('status', ['not-a-status', None, True, 5])
def test_invalid_direct_review_status_is_rejected_without_mutation(status):
    store = EventStore()
    try:
        store.add(event('original'))
        with pytest.raises(ValueError, match='event status'):
            store.update_status('original', status)
        assert store.query()[0].status == 'pending'
        assert store._connection.in_transaction is False
    finally:
        store.close()


def test_corrupt_persisted_details_cannot_commit_a_review_that_fails_to_decode():
    store = EventStore()
    try:
        store.add(event('original'))
        store._connection.execute("UPDATE events SET details_json='not-json'")
        store._connection.commit()
        with pytest.raises(ValueError):
            store.update_status('original', 'confirmed')
        assert store._connection.in_transaction is False
        row = store._connection.execute('SELECT status,details_json FROM events').fetchone()
        assert row['status'] == 'pending' and row['details_json'] == 'not-json'
    finally:
        store.close()
