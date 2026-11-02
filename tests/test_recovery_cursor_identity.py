import hashlib
import sqlite3

import pytest

from edge_hub.events import Event, EventStore
from tools import check_event_backup_recovery as recovery


def offline_source(tmp_path, *, empty=False):
    path = tmp_path / 'source.sqlite3'
    store = EventStore(path)
    for index in range(3):
        store.add(Event(id=f'event-{index}', type='robot_fault', zone='fixture',
                        at_ms=3-index, severity='notice'))
    if empty:
        store.clear()
    store.close()
    return path, path.read_bytes()


@pytest.mark.parametrize('empty', [False, True])
def test_existing_cursor_lineage_and_empty_high_water_are_preserved(tmp_path, empty):
    path, raw = offline_source(tmp_path, empty=empty)
    report = recovery.check(path, hashlib.sha256(raw).hexdigest())
    assert report['existing_sequence_and_high_water_preserved'] is True
    assert report['existing_stream_identity_preserved'] is True
    assert report['pagination_identity_and_order_verified'] is True
    assert path.read_bytes() == raw


@pytest.mark.parametrize('mutation,message', [
    ('sequence', 'sequence or high water'), ('watermark', 'sequence or high water'),
    ('stream', 'stream identity'),
])
def test_copy_cursor_corruption_cannot_hide_behind_equal_event_contents(tmp_path, monkeypatch, mutation, message):
    path, raw = offline_source(tmp_path)

    class ChangedCopy(EventStore):
        def __init__(self, destination):
            super().__init__(destination)
            sql = {
                'sequence': 'UPDATE event_ingest_sequence SET seq=seq+100',
                'watermark': "UPDATE sqlite_sequence SET seq=seq+100 WHERE name='event_ingest_sequence'",
                'stream': "UPDATE event_stream_metadata SET stream_id='00000000000000000000000000000000'",
            }[mutation]
            self._connection.execute(sql)
            self._connection.commit()

    monkeypatch.setattr(recovery, 'EventStore', ChangedCopy)
    with pytest.raises(ValueError, match=message):
        recovery.check(path, hashlib.sha256(raw).hexdigest())
    assert path.read_bytes() == raw


def test_same_count_wrong_page_order_is_rejected(tmp_path, monkeypatch):
    path, raw = offline_source(tmp_path)
    original_page = EventStore.page

    def reversed_page(self, **kwargs):
        page = original_page(self, **kwargs)
        page['items'] = list(reversed(page['items']))
        return page

    monkeypatch.setattr(recovery.EventStore, 'page', reversed_page)
    with pytest.raises(ValueError, match='identity or order'):
        recovery.check(path, hashlib.sha256(raw).hexdigest())
    assert path.read_bytes() == raw


def test_legacy_backup_does_not_claim_nonexistent_cursor_was_preserved(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as database:
        database.execute('CREATE TABLE events (id TEXT PRIMARY KEY,type TEXT,zone TEXT,at_ms INTEGER,'
                         'severity TEXT,evidence TEXT,details_json TEXT,status TEXT)')
        database.execute("INSERT INTO events VALUES ('old','robot_fault','fixture',1,'notice',NULL,'{}','pending')")
    raw = path.read_bytes()
    report = recovery.check(path, hashlib.sha256(raw).hexdigest())
    assert report['existing_sequence_and_high_water_preserved'] is None
    assert report['existing_stream_identity_preserved'] is None
    assert report['pagination_identity_and_order_verified'] is True
    assert path.read_bytes() == raw
