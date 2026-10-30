import sqlite3

import pytest
import test_cloud_http_app

prepared = test_cloud_http_app.prepared
seeded = test_cloud_http_app.seeded
keys = test_cloud_http_app.keys
api = test_cloud_http_app.api
URL = '/api/v1/service-desk/requests'
BODY = {'submission_id': 'f' * 32, 'kind': 'water', 'location': 'A座12樓B室',
        'message': 'PUBLIC-SYNTHETIC-WATER', 'confirmed': True}


class CommitFault:
    """A real underlying commit/rollback, with a one-shot missing reply."""
    def __init__(self, db, mode, error):
        self.db, self.mode, self.error, self.faults = db, mode, error, 0

    def __getattr__(self, name):
        return getattr(self.db, name)

    def __enter__(self):
        self.db.__enter__()
        return self

    def __exit__(self, kind, value, traceback):
        if kind is not None or self.mode is None:
            return self.db.__exit__(kind, value, traceback)
        mode, self.mode = self.mode, None
        self.faults += 1
        error = self.error('PRIVATE SQL/path/key/detail')
        if mode == 'before':
            self.db.__exit__(type(error), error, None)
        else:
            self.db.__exit__(None, None, None)
        raise error


def assert_private_failure(response, outcome, policy):
    assert response.status_code == 503
    result = response.json()
    assert result['code'] == 'storage_unavailable'
    assert result['operation_outcome'] == outcome and result['retry_policy'] == policy
    assert 'PRIVATE' not in response.text and BODY['location'] not in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert 'retry-after' not in response.headers


@pytest.mark.parametrize('mode', ['before', 'after'])
@pytest.mark.parametrize('error', [sqlite3.OperationalError, OSError])
def test_missing_commit_reply_never_claims_not_written_and_same_id_replay_never_duplicates(api, mode, error):
    store = api.services.cases
    wrapped = CommitFault(store.db, mode, error)
    store.db = wrapped
    response = api.client.post(URL, headers=api.resident, json=BODY)
    assert_private_failure(response, 'unknown', 'same_submission_id_same_content')
    assert wrapped.faults == 1
    count = store.db.execute('SELECT COUNT(*) FROM service_cases').fetchone()[0]
    assert count == (2 if mode == 'after' else 1)
    replay = api.client.post(URL, headers=api.resident, json=BODY)
    assert replay.status_code == 200 and replay.json()['case_number'] == 2
    assert replay.json()['replayed'] is (mode == 'after')
    again = api.client.post(URL, headers=api.resident, json=BODY)
    assert again.json()['id'] == replay.json()['id'] and again.json()['replayed']
    assert store.db.execute('SELECT COUNT(*) FROM service_cases').fetchone()[0] == 2
    assert store.db.execute('SELECT MAX(ordinal) FROM service_case_numbers').fetchone()[0] == 2
    assert store.db.execute('SELECT COUNT(*) FROM service_case_activity').fetchone()[0] == 2
    conflict = api.client.post(URL, headers=api.resident, json={**BODY, 'message': 'DIFFERENT'})
    assert conflict.status_code == 409
    assert api.calls == [] and api.search.await_count == 0


@pytest.mark.parametrize('error', [sqlite3.OperationalError, OSError])
def test_staff_update_after_commit_requires_reading_revision_and_cannot_apply_twice(api, error):
    receipt = api.client.post(URL, headers=api.resident, json=BODY).json()
    store = api.services.cases
    store.db = CommitFault(store.db, 'after', error)
    target = URL + '/' + receipt['id']
    update = {'status': 'acknowledged', 'expected_revision': 1, 'note': 'PUBLIC-SYNTHETIC-NOTE'}
    assert_private_failure(api.client.patch(target, headers=api.staff, json=update),
                           'unknown', 'read_current_revision')
    listed = api.client.get(URL, headers=api.staff).json()['items']
    row = next(item for item in listed if item['id'] == receipt['id'])
    assert row['revision'] == 2 and row['note'] == update['note']
    assert api.client.patch(target, headers=api.staff, json=update).status_code == 409
    count = store.db.execute('SELECT COUNT(*) FROM service_case_activity WHERE case_id=?', (receipt['id'],)).fetchone()[0]
    assert count == 2  # creation + one acknowledged update


@pytest.mark.parametrize('error', [sqlite3.OperationalError, OSError])
def test_read_error_is_redacted_without_mutation_or_retry(api, monkeypatch, error):
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise error('PRIVATE SQL/path/key/detail')

    monkeypatch.setattr(api.services.cases, 'list', fail)
    assert_private_failure(api.client.get(URL, headers=api.staff), 'read_unavailable', 'manual_retry')
    assert len(calls) == 1
    assert api.services.cases.db.execute('SELECT COUNT(*) FROM service_cases').fetchone()[0] == 1


def test_audit_begin_failure_says_operation_not_attempted_and_blocks_the_update(api, monkeypatch):
    receipt = api.client.post(URL, headers=api.resident, json=BODY).json()

    def fail(*args):
        raise sqlite3.OperationalError('PRIVATE-AUDIT')

    monkeypatch.setattr(api.services.journal, 'begin', fail)
    assert_private_failure(api.client.patch(URL + '/' + receipt['id'], headers=api.staff,
        json={'status': 'acknowledged', 'expected_revision': 1}), 'not_attempted', 'manual_retry')
    assert api.services.cases.db.execute('SELECT revision FROM service_cases WHERE id=?', (receipt['id'],)).fetchone()[0] == 1


def test_audit_finish_failure_does_not_turn_a_confirmed_commit_into_a_failed_write(api, monkeypatch):
    receipt = api.client.post(URL, headers=api.resident, json=BODY).json()

    def fail(*args):
        raise OSError('PRIVATE-AUDIT')

    monkeypatch.setattr(api.services.journal, 'finish', fail)
    response = api.client.patch(URL + '/' + receipt['id'], headers=api.staff,
        json={'status': 'acknowledged', 'expected_revision': 1})
    assert response.status_code == 200 and response.json()['revision'] == 2
    intent = api.services.journal.recent()[0]
    assert intent['method'] == 'PATCH' and intent['status'] is None


def test_validation_conflict_auth_and_success_statuses_are_not_relabelled_as_storage_faults(api):
    assert api.client.post(URL, headers=api.resident, json={}).status_code == 422
    assert api.client.get(URL, headers=api.resident).status_code == 403
    assert api.client.get(URL).status_code == 401
    assert api.client.post(URL, headers=api.resident, json=BODY).status_code == 200
    assert api.client.post(URL, headers=api.resident, json={**BODY, 'message': 'OTHER'}).status_code == 409


def test_failed_audit_cleanup_never_masks_the_original_unhandled_error(api, monkeypatch):
    def original_error(**kwargs):
        raise RuntimeError('SYNTHETIC-ORIGINAL-FAULT')

    def cleanup_error(*args):
        raise OSError('SYNTHETIC-CLEANUP-FAULT')

    monkeypatch.setattr(api.services.cases, 'list', original_error)
    monkeypatch.setattr(api.services.journal, 'finish', cleanup_error)
    with pytest.raises(RuntimeError, match='SYNTHETIC-ORIGINAL-FAULT'):
        api.client.get(URL, headers=api.staff)
