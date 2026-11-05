import sqlite3
from contextlib import contextmanager

import pytest
import test_cloud_photo_api

prepared = test_cloud_photo_api.prepared
seeded = test_cloud_photo_api.seeded
keys = test_cloud_photo_api.keys
api = test_cloud_photo_api.api
photographs = test_cloud_photo_api.photographs
EVENT = test_cloud_photo_api.EVENT
FOLLOW = f'/api/v1/patrol/events/{EVENT}/followup'


def test_case_search_filters_are_staff_only_paged_and_do_not_change_alert_counts(api):
    from edge_hub.service_desk import ResidentCase
    for index in range(3):
        item = api.services.cases.create(ResidentCase(submission_id=f'{900 + index:032x}',
            kind='human_support' if index == 2 else 'water', message='合成漏水跟進', location='1樓1室', confirmed=True))
        with api.services.cases.db:
            api.services.cases.db.execute('UPDATE service_cases SET status=?,created_at_ms=? WHERE id=?',
                ('resolved' if index == 0 else 'new', 1793635200000 + index, item['id']))
    path = '/api/v1/service-desk/requests'
    params = {'q': '一樓一室', 'state': 'new', 'group': 'requests', 'date_from': '2026-11-03',
              'date_to': '2026-11-03', 'sort': 'created_asc', 'limit': 1}
    assert api.client.get(path, params=params).status_code == 401
    assert api.client.get(path, params=params, headers=api.resident).status_code == 403
    reply = api.client.get(path, params=params, headers=api.staff)
    assert reply.status_code == 200, reply.text
    result = reply.json()
    assert result['matched_total'] == 1 and len(result['items']) == 1 and not result['has_more']
    assert result['counts']['resolved'] >= 1  # Global alerts remain independent of the search.
    params['group'] = 'care'
    assert api.client.get(path, params=params, headers=api.staff).json()['matched_total'] == 1
    assert api.client.get(path, params={'date_from': '2026-02-30'}, headers=api.staff).status_code == 422
    assert not api.calls and api.search.await_count == 0


def test_report_snapshot_filters_before_pagination_and_validation_remains_closed(api):
    from edge_hub.events import Event
    for index in range(4):
        api.services.events.add(Event(id=f'filter-{index}', type='litter_detected', zone='合成大堂',
            at_ms=1793635200000 + index, severity='notice', details={'is_test': index < 2}))
    path = '/api/v1/patrol/workbench'
    params = {'q': '垃圾', 'live_only': 'true', 'limit': 1, 'offset': 1, 'state': 'pending',
              'date_from': '2026-11-03', 'date_to': '2026-11-03'}
    reply = api.client.get(path, params=params, headers=api.staff)
    assert reply.status_code == 200, reply.text
    result = reply.json()
    assert result['matched_total'] == 2 and not result['has_more']
    assert result['events'][0]['id'] == 'filter-2'
    for invalid in ({'offset': -1}, {'limit': 101}, {'sort': 'private'}, {'q': 'x' * 121}):
        assert api.client.get(path, params=invalid, headers=api.staff).status_code == 422
    assert api.client.get(path, params=params, headers=api.resident).status_code == 403
    assert not api.calls and api.search.await_count == 0


def test_workbench_snapshot_is_staff_only_and_bulk_reads_links(photographs, monkeypatch):
    api, _, _ = photographs
    case = api.client.post(FOLLOW, headers=api.staff).json()
    path = '/api/v1/patrol/workbench'
    assert api.client.get(path).status_code == 401
    assert api.client.get(path, headers=api.resident).status_code == 403
    manager = api.services.cases.patrol_sync.__self__
    statements = []
    connection = api.services.cases.db
    execute = type(connection).execute
    def observe(self, statement, *args, **kwargs):
        if self is connection:
            statements.append(statement)
        return execute(self, statement, *args, **kwargs)
    monkeypatch.setattr(type(connection), 'execute', observe)
    response = api.client.get(path, headers=api.staff)
    assert response.status_code == 200, response.text
    value = response.json()
    assert any(item['id'] == EVENT for item in value['events'])
    assert value['stats']['total'] >= 1
    assert value['followups']['items'][0]['case_number'] == case['case_number']
    assert sum('SELECT' in line.upper() and 'PATROL_CASE_LINKS' in line.upper() for line in statements) == 1
    assert not any('INSERT' in line.upper() or 'UPDATE' in line.upper() for line in statements)
    assert manager is not None and not api.calls


def test_events_stats_and_followups_are_staff_only_without_any_robot_calls(api):
    for path in ('/api/v1/events?limit=100', '/api/v1/event-stats', '/api/v1/patrol/followups'):
        assert api.client.get(path).status_code == 401
        assert api.client.get(path, headers=api.resident).status_code == 403
        reply = api.client.get(path, headers=api.staff)
        assert reply.status_code == 200 and reply.headers['cache-control'] == 'no-store'
    assert api.client.get('/api/v1/events?limit=1000', headers=api.staff).status_code == 422
    assert api.client.get('/api/v1/patrol/followups?ids=../private', headers=api.staff).status_code == 422
    assert api.client.post('/api/v1/ep/fleet/connect', headers=api.staff, json={}).status_code == 404
    assert not api.calls and api.search.await_count == 0


def test_robot_relay_requires_existing_staff_login_without_google_or_hardware(api):
    path = '/api/v1/robot/ep/fleet'
    assert api.client.get(path).status_code == 401
    assert api.client.get(path, headers=api.resident).status_code == 403
    # This fixture has no onsite presentation/endpoint; fail closed before relay.
    assert api.client.get(path, headers=api.staff).status_code in (404, 503)
    assert not api.calls and api.search.await_count == 0


def test_patrol_three_photos_to_one_numbered_case_and_staff_progress_mirror(photographs):
    api, _, _ = photographs
    before = api.services.cases.list()['counts']['new']
    result = api.client.post(FOLLOW, headers=api.staff)
    assert result.status_code == 200, result.text
    case = result.json()
    assert type(case['case_number']) is int and case['case_number'] > 0
    assert api.client.post(FOLLOW, headers=api.staff).json()['case_id'] == case['case_id']
    assert api.services.cases.list()['counts']['new'] == before + 1
    update = api.client.patch('/api/v1/service-desk/requests/' + case['case_id'], headers=api.staff,
        json={'expected_revision': case['revision'], 'status': 'acknowledged', 'assignee': '管理團隊', 'note': '職員準備前往核實。'})
    assert update.status_code == 200
    assert api.services.events.get_event(EVENT).status == 'confirmed'
    assert api.client.get(f'/api/v1/patrol/events/{EVENT}/photo', headers=api.staff).status_code == 200
    snapshot = api.client.get('/api/v1/patrol/followups?ids=' + EVENT, headers=api.staff).json()['items'][0]
    assert snapshot['note'] == '職員準備前往核實。' and snapshot['status'] == 'acknowledged'
    stale = api.client.patch('/api/v1/events/' + EVENT, headers=api.staff,
                            json={'status': 'resolved', 'expected_revision': case['revision']})
    assert stale.status_code == 409
    finished = api.client.patch('/api/v1/events/' + EVENT, headers=api.staff,
        json={'status': 'resolved', 'expected_revision': snapshot['revision']})
    assert finished.status_code == 200 and finished.json()['status'] == 'resolved'
    final_case = next(row for row in api.services.cases.list()['items'] if row['id'] == case['case_id'])
    assert final_case['status'] == 'resolved'
    for side in ('event', 'left', 'right'):
        assert api.client.get(f'/api/v1/patrol/events/{EVENT}/photo?side={side}', headers=api.staff).status_code == 200
    assert not api.calls and api.search.await_count == 0


@pytest.mark.parametrize('damage', ['missing_side', 'tombstone', 'tampered'])
def test_incomplete_deleted_or_changed_photo_bundle_cannot_create_case(photographs, damage):
    api, _, photos = photographs
    before = api.services.cases.list()['counts']
    key = photos[1]['path']
    with api.services.photos.lock, api.services.photos.db:
        if damage == 'missing_side':
            api.services.photos.db.execute('DELETE FROM cloud_photos WHERE key=?', (key,))
        elif damage == 'tampered':
            api.services.photos.db.execute('UPDATE cloud_photos SET content=? WHERE key=?', (b'changed', key))
        else:
            api.services.ledger.append([{'kind': 'event', 'target': EVENT, 'revision': 1, 'erased_ms': 2}])
    response = api.client.post(FOLLOW, headers=api.staff)
    assert response.status_code in (404, 409, 410, 503)
    assert api.services.cases.list()['counts'] == before


def test_purged_event_cannot_generate_a_staff_followup(photographs):
    api,_,_=photographs
    before=api.services.cases.list()['counts']
    api.services.ledger.append([{'kind':'event_purge','target':EVENT,'revision':1,'erased_ms':2}])
    assert api.client.post(FOLLOW,headers=api.staff).status_code==410
    assert api.services.cases.list()['counts']==before


def test_unexpected_review_fields_or_resident_claims_never_update(api):
    path = '/api/v1/events/synthetic-event'
    assert api.client.patch(path, headers=api.resident, json={'status': 'resolved'}).status_code == 403
    assert api.client.patch(path, headers=api.staff, json={'status': 'resolved', 'role': 'staff'}).status_code == 422
    assert api.services.events.get_event('synthetic-event').status == 'pending'


def test_lost_photo_commit_reply_keeps_outbox_and_recovery_does_not_restart_90_day_clock(photographs, monkeypatch):
    api, _, _ = photographs
    case = api.client.post(FOLLOW, headers=api.staff).json()
    path = '/api/v1/service-desk/requests/' + case['case_id']
    confirmed = api.client.patch(path, headers=api.staff,
        json={'expected_revision': case['revision'], 'status': 'acknowledged'}).json()
    photos = api.services.photos
    original = photos.transaction
    armed = [True]

    @contextmanager
    def lost_reply():
        outer = not photos.db.in_transaction
        with original():
            yield
        if outer and armed[0]:
            armed[0] = False
            raise sqlite3.OperationalError('synthetic lost commit acknowledgement')

    monkeypatch.setattr(photos, 'transaction', lost_reply)
    response = api.client.patch(path, headers=api.staff,
        json={'expected_revision': confirmed['revision'], 'status': 'resolved'})
    assert response.status_code == 200 and response.json()['patrol_sync_pending'] is True
    with photos.lock:
        before = tuple(photos.db.execute('SELECT * FROM cloud_photo_retention WHERE event_id=?', (EVENT,)).fetchone())
    assert before[2] == 'resolved' and type(before[3]) is int
    monkeypatch.setattr(photos, 'transaction', original)
    manager = api.services.cases.patrol_sync.__self__
    with api.services.scope():
        manager.flush_case(case['case_id'])
        manager.flush_case(case['case_id'])
    after = tuple(photos.db.execute('SELECT * FROM cloud_photo_retention WHERE event_id=?', (EVENT,)).fetchone())
    assert after == before
    link = api.client.get('/api/v1/patrol/followups?ids=' + EVENT, headers=api.staff).json()['items'][0]
    assert link['sync_pending'] == 0
    assert api.client.get(f'/api/v1/patrol/events/{EVENT}/photo', headers=api.staff).status_code == 200
