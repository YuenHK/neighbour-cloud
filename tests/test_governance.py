
from edge_hub.events import EventStore
from edge_hub.governance import AccessJournal, private_staff_path, retention_preview
from edge_hub.service_desk import ResidentCase, ReviewCase, ServiceDeskStore


def test_access_journal_never_stores_payload_query_or_key(tmp_path):
    journal = AccessJournal(tmp_path/'journal.sqlite3')
    identity = journal.begin('GET', '/api/v1/service-desk/requests/'+'a'*32, 'staff')
    journal.finish(identity, 200)
    row = journal.recent()[0]
    assert row['route'].endswith('/{id}') and row['status'] == 200
    assert len(row['object_hash']) == 64 and 'a'*32 not in str(row)
    assert private_staff_path('/api/v1/patrol/events/a/photo', 'GET')
    assert not private_staff_path('/api/v1/robot/stop', 'POST')
    assert not private_staff_path('/api/v1/service-desk/requests', 'POST')


def test_retention_preview_uses_completion_time_never_deletes_memory_or_live_case(tmp_path):
    cases, events = ServiceDeskStore(tmp_path/'cases.sqlite3'), EventStore(tmp_path/'events.sqlite3')
    try:
        first = cases.create(ResidentCase(submission_id='a'*32, kind='general', message='測試維修', confirmed=True))
        cases.review(first['id'], ReviewCase(status='resolved', expected_revision=1))
        cases.create(ResidentCase(submission_id='b'*32, kind='general', message='未完成', confirmed=True))
        with cases.db:
            cases.db.execute('UPDATE service_cases SET created_at_ms=1,updated_at_ms=1')
        result = retention_preview(cases, events, now_ms=100*86400000)
        assert result['due_completed_cases'] == 1 and not result['automatic_deletion_enabled']
        assert cases.db.execute('SELECT COUNT(*) FROM service_cases').fetchone()[0] == 2
        assert 'MB842' in result['excluded'] and not result['backup_cleanup_verified']
    finally:
        cases.close(); events.close()
