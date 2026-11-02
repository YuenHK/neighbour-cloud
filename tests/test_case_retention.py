import sqlite3

from edge_hub.case_retention import expire_cases, expire_event_photos
from edge_hub.events import Event, EventStore
from edge_hub.service_desk import ResidentCase, ReviewCase, ServiceDeskStore


def test_90_days_erases_case_and_managed_backup_preserves_open_cases_and_memory(tmp_path):
    root = tmp_path/'runtime'
    root.mkdir()
    cases = ServiceDeskStore(root/'service-desk.sqlite3')
    try:
        case = cases.create(ResidentCase(submission_id='a'*32, kind='human_support', message='private problem', contact='private contact', confirmed=True))
        live = cases.create(ResidentCase(submission_id='b'*32, kind='general', message='still open', confirmed=True))
        backup = root/'previous'/'cases-before.sqlite3'
        backup.parent.mkdir()
        with sqlite3.connect(backup) as copied:
            cases.db.backup(copied)
        cases.review(case['id'], ReviewCase(status='resolved', expected_revision=1))
        with cases.db:
            cases.db.execute('UPDATE service_cases SET updated_at_ms=1 WHERE id=?', (case['id'],))
            cases.db.execute('CREATE TABLE resident_memories(id TEXT,text TEXT)')
            cases.db.execute("INSERT INTO resident_memories VALUES('MB842','must stay')")
        assert expire_cases(cases, root, now_ms=89*86400000)['erased_cases'] == 0
        assert expire_cases(cases, root, now_ms=91*86400000)['erased_cases'] == 1
        assert cases.db.execute('SELECT message FROM service_cases WHERE id=?', (live['id'],)).fetchone()[0] == 'still open'
        assert cases.db.execute('SELECT text FROM resident_memories WHERE id=?', ('MB842',)).fetchone()[0] == 'must stay'
        with sqlite3.connect(backup) as copied:
            assert copied.execute('SELECT contact FROM service_cases WHERE id=?', (case['id'],)).fetchone()[0] == ''
            assert copied.execute('SELECT message FROM service_cases WHERE id=?', (live['id'],)).fetchone()[0] == 'still open'
        assert expire_cases(cases, root, now_ms=91*86400000)['erased_cases'] == 0
    finally:
        cases.close()


def test_photo_clock_is_completion_not_capture_and_reopen_cancels_expiry(tmp_path):
    store = EventStore(tmp_path/'events.sqlite3')
    try:
        path = tmp_path/'events'/'test-blurred.jpg'
        path.parent.mkdir()
        path.write_bytes(b'private photograph')
        store.add(Event(id='test', type='litter_detected', zone='local', at_ms=1, severity='notice', evidence='events/test-blurred.jpg'))
        assert expire_event_photos(store, tmp_path, now_ms=200*86400000)['expired_event_candidates'] == 0
        assert path.exists()
        store.update_status('test', 'resolved')
        with store._connection:
            store._connection.execute('UPDATE event_completion SET completed_at_ms=1')
        store.update_status('test', 'pending')
        assert expire_event_photos(store, tmp_path, now_ms=200*86400000)['expired_event_candidates'] == 0
        store.update_status('test', 'resolved')
        with store._connection:
            store._connection.execute('UPDATE event_completion SET completed_at_ms=1')
        assert expire_event_photos(store, tmp_path, now_ms=91*86400000)['expired_event_candidates'] == 1
        assert not path.exists() and store.get_event('test').details['retention_erased']
    finally:
        store.close()


def test_unrecognised_backup_stops_before_live_private_fields_are_changed(tmp_path):
    root = tmp_path/'runtime'
    root.mkdir()
    cases = ServiceDeskStore(root/'service-desk.sqlite3')
    try:
        case = cases.create(ResidentCase(submission_id='a'*32, kind='general', message='must remain on failure', confirmed=True))
        cases.review(case['id'], ReviewCase(status='resolved', expected_revision=1))
        with cases.db:
            cases.db.execute('UPDATE service_cases SET updated_at_ms=1')
        backup = root/'old'/'cases-before.sqlite3'
        backup.parent.mkdir()
        with sqlite3.connect(backup) as db:
            db.execute('CREATE TABLE service_cases(id TEXT)')
        import pytest
        with pytest.raises(ValueError, match='unrecognised_case_backup'):
            expire_cases(cases, root, now_ms=91*86400000)
        assert cases.db.execute('SELECT message FROM service_cases').fetchone()[0] == 'must remain on failure'
    finally:
        cases.close()
