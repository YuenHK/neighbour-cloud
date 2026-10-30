import hashlib
import io
import json
import sqlite3
import time

import pytest
import test_cloud_http_app
from PIL import Image

prepared = test_cloud_http_app.prepared
seeded = test_cloud_http_app.seeded
keys = test_cloud_http_app.keys
api = test_cloud_http_app.api
DAY = 86_400_000
EVENT = 'c' * 32
URL = f'/api/v1/patrol/events/{EVENT}/photo'


@pytest.fixture
def photographs(api):
    from edge_hub.events import Event

    photos, images = [], {}
    for number, (side, color) in enumerate(zip(('event', 'left', 'right'), ('green', 'blue', 'yellow'))):
        buffer = io.BytesIO()
        Image.new('RGB', (16, 16), color).save(buffer, format='JPEG')
        image = buffer.getvalue()
        key = 'events/ep-patrol/' + str(number) * 32 + '.jpg'
        digest = hashlib.sha256(image).hexdigest()
        photos.append({'side': side, 'path': key, 'sha256': digest, 'frame_key': 'frame-' + side})
        images[side] = image
        api.services.photos.put(EVENT, side, key, image, reviewed=True, now_ms=1)
    details = {'source': 'ep_patrol_local', 'review_required': True, 'robot_sn': 'SYNTHETIC',
               'frame_key': 'frame-event', 'photo_sha256': photos[0]['sha256'], 'photos': photos}
    api.services.events.add(Event(id=EVENT, type='litter_detected', zone='PUBLIC', at_ms=1,
        severity='notice', evidence=photos[0]['path'], details=details))
    api.services.photos.event_state(EVENT, 'pending', 1)
    return api, images, photos


def completed(api, *, when, status='resolved'):
    api.services.events.update_status(EVENT, status)
    with api.services.events._lock, api.services.events._connection:
        api.services.events._connection.execute('UPDATE event_completion SET completed_at_ms=? WHERE event_id=?',
                                                (when, EVENT))
    api.services.photos.event_state(EVENT, status, 2, completed_ms=when)


def test_three_photos_are_staff_only_bound_bytes_with_no_cache_or_local_file(photographs, seeded):
    api, images, _ = photographs
    before = api.services.photos.db.execute('SELECT * FROM cloud_photos ORDER BY key').fetchall()
    for side, image in images.items():
        response = api.client.get(URL, params={'side': side}, headers=api.staff)
        assert response.status_code == 200
        assert response.content == image
        assert response.headers['content-type'] == 'image/jpeg'
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert 'etag' not in response.headers and 'last-modified' not in response.headers
    after = api.services.photos.db.execute('SELECT * FROM cloud_photos ORDER BY key').fetchall()
    assert [tuple(row) for row in before] == [tuple(row) for row in after]
    assert api.calls == [] and api.search.await_count == 0
    assert not list(seeded[1].rglob('*.jpg'))
    recent = api.services.journal.recent()
    assert sum(row['route'].endswith('/photo') and row['status'] == 200 for row in recent) == 3
    assert all(EVENT not in row['route'] for row in recent)


def test_auth_origin_and_arbitrary_path_never_read_photo(photographs, monkeypatch):
    api, _, _ = photographs
    reads = []
    monkeypatch.setattr(api.services.photos, 'get', lambda key: reads.append(key))
    assert api.client.get(URL).status_code == 401
    assert api.client.get(URL, headers=api.resident).status_code == 403
    assert api.client.get(URL, headers={**api.staff, 'Origin': 'https://other.example'}).status_code == 403
    assert api.client.get(URL, params={'side': '../../PRIVATE'}, headers=api.staff).status_code == 422
    assert api.client.get(URL, params={'path': 'C:/PRIVATE/file.jpg'}, headers=api.staff).status_code == 400
    assert api.client.get(URL + '?side=left&side=right', headers=api.staff).status_code == 400
    assert api.client.get('/api/v1/patrol/events/no-such/photo', headers=api.staff).status_code == 404
    for tail in ('privacy-preview', 'privacy-approve', 'connect', 'photo/extra'):
        assert api.client.post(URL.rsplit('/', 1)[0] + '/' + tail, headers=api.staff, json={}).status_code == 404
    assert reads == []


@pytest.mark.parametrize('field,value', [('event_id', 'another-event'), ('side', 'right'), ('digest', 'f' * 64)])
def test_photo_cannot_be_substituted_from_other_event_or_side(photographs, field, value):
    api, _, photos = photographs
    with api.services.photos.db:
        # Use a free side so the damaged metadata does not hit the UNIQUE constraint.
        if field == 'side':
            api.services.photos.db.execute('DELETE FROM cloud_photos WHERE side=?', (value,))
        api.services.photos.db.execute(f'UPDATE cloud_photos SET {field}=? WHERE key=?', (value, photos[0]['path']))
    response = api.client.get(URL, headers=api.staff)
    assert response.status_code == 503 and 'another-event' not in response.text
    assert photos[0]['path'] not in response.text


def test_completed_retention_uses_matching_completion_clock_not_capture_time(photographs):
    api, images, _ = photographs
    now = int(time.time() * 1000)
    completed(api, when=now - 89 * DAY)
    assert api.client.get(URL, headers=api.staff).content == images['event']
    # Simulate a legitimately older imported completion, without invoking any cleaner.
    for db, sql in ((api.services.events._connection, 'UPDATE event_completion SET completed_at_ms=? WHERE event_id=?'),
                    (api.services.photos.db, 'UPDATE cloud_photo_retention SET completed_ms=? WHERE event_id=?')):
        with db:
            db.execute(sql, (now - 90 * DAY, EVENT))
    assert api.client.get(URL, headers=api.staff).status_code == 410
    assert api.services.photos.db.execute('SELECT COUNT(*) FROM cloud_photos').fetchone()[0] == 3
    assert api.services.ledger.checkpoint()['seq'] == 1  # GET never deletes or appends a receipt.


@pytest.mark.parametrize('damage', ['missing', 'status', 'clock', 'future', 'revision'])
def test_missing_or_inconsistent_retention_fails_closed(photographs, damage):
    api, _, _ = photographs
    completed(api, when=int(time.time() * 1000) - DAY)
    db = api.services.photos.db
    with db:
        if damage == 'missing':
            db.execute('DELETE FROM cloud_photo_retention WHERE event_id=?', (EVENT,))
        else:
            field, value = {'status': ('status', 'pending'), 'clock': ('completed_ms', 1),
                            'future': ('completed_ms', int(time.time() * 1000) + DAY),
                            'revision': ('revision', 0)}[damage]
            db.execute(f'UPDATE cloud_photo_retention SET {field}=? WHERE event_id=?', (value, EVENT))
    response = api.client.get(URL, headers=api.staff)
    assert response.status_code == 503 and 'sqlite' not in response.text.lower()


def test_committed_deletion_intent_blocks_even_before_photo_cleanup(photographs):
    api, _, _ = photographs
    api.services.ledger.append([{'kind': 'event', 'target': EVENT, 'revision': 1, 'erased_ms': 1}])
    assert api.client.get(URL, headers=api.staff).status_code == 410
    assert api.services.photos.db.execute('SELECT COUNT(*) FROM cloud_photos').fetchone()[0] == 3


def test_invalid_deletion_ledger_is_never_treated_as_no_erasure(photographs):
    api, _, _ = photographs
    with api.services.ledger.db:
        api.services.ledger.db.execute('UPDATE cloud_deletion_head SET signature=?', ('0' * 64,))
    assert api.client.get(URL, headers=api.staff).status_code == 503


def test_journal_unavailable_blocks_before_photo_read(photographs, monkeypatch):
    api, _, _ = photographs
    reads = []
    monkeypatch.setattr(api.services.photos, 'get', lambda key: reads.append(key))

    def fail(*args):
        raise OSError('PRIVATE-JOURNAL-PATH')

    monkeypatch.setattr(api.services.journal, 'begin', fail)
    response = api.client.get(URL, headers=api.staff)
    assert response.status_code == 503 and 'PRIVATE' not in response.text and reads == []


def test_photo_capacity_and_deadline_release_slots_without_loading_bytes(photographs, monkeypatch):
    from deploy.cloud.photo_api import PhotoUnavailable, StaffPhotos

    api, images, _ = photographs
    clock = [0]
    reader = StaffPhotos(api.services, clock=lambda: clock[0])
    assert reader.slots.acquire(False) and reader.slots.acquire(False)
    with pytest.raises(PhotoUnavailable) as busy:
        reader.read(EVENT, 'event')
    assert busy.value.status == 503
    reader.slots.release()
    reader.slots.release()
    original = api.services.ledger.records
    reads = []

    def delayed(head):
        clock[0] += 6
        return original(head)

    with monkeypatch.context() as patch:
        patch.setattr(api.services.ledger, 'records', delayed)
        patch.setattr(api.services.photos, 'get', lambda key: reads.append(key))
        with pytest.raises(PhotoUnavailable) as late:
            reader.read(EVENT, 'event')
        assert late.value.status == 503 and reads == []
    assert reader.read(EVENT, 'event') == images['event']


@pytest.mark.parametrize('table', ['cloud_erased_events', 'cloud_photo_tombstones'])
def test_photo_tombstone_cannot_be_bypassed_by_retained_bytes(photographs, table):
    api, _, photos = photographs
    db = api.services.photos.db
    with db:
        if table == 'cloud_erased_events':
            db.execute('INSERT INTO cloud_erased_events VALUES(?,1)', (EVENT,))
        else:
            db.execute('INSERT INTO cloud_photo_tombstones VALUES(?,?,1)', (photos[0]['path'], EVENT))
    assert api.client.get(URL, headers=api.staff).status_code == 410


def test_changed_event_or_new_erase_during_read_cannot_return_image(photographs, monkeypatch):
    api, _, _ = photographs
    original = api.services.photos.get

    def changed(key):
        result = original(key)
        api.services.events.update_status(EVENT, 'confirmed')
        return result

    monkeypatch.setattr(api.services.photos, 'get', changed)
    assert api.client.get(URL, headers=api.staff).status_code == 409
    monkeypatch.setattr(api.services.photos, 'get', original)
    api.services.photos.event_state(EVENT, 'confirmed', 2)

    def erase(key):
        result = original(key)
        api.services.ledger.append([{'kind': 'event', 'target': EVENT, 'revision': 2, 'erased_ms': 1}])
        return result

    monkeypatch.setattr(api.services.photos, 'get', erase)
    assert api.client.get(URL, headers=api.staff).status_code == 409


def test_photo_storage_error_redacted_and_gate_recovers_without_retries(photographs, monkeypatch):
    api, images, _ = photographs
    original = api.services.photos.get
    calls = []

    def fail(key):
        calls.append(key)
        raise sqlite3.OperationalError('PRIVATE SQL/key/path')

    monkeypatch.setattr(api.services.photos, 'get', fail)
    for _ in range(3):
        response = api.client.get(URL, headers=api.staff)
        assert response.status_code == 503 and 'PRIVATE' not in response.text
    assert len(calls) == 3
    monkeypatch.setattr(api.services.photos, 'get', original)
    assert api.client.get(URL, headers=api.staff).content == images['event']


@pytest.mark.parametrize('damage', ['bytes', 'large', 'manifest'])
def test_corrupt_bytes_and_manifest_never_return_private_database_content(photographs, damage):
    api, _, photos = photographs
    if damage == 'manifest':
        with api.services.events._connection:
            api.services.events._connection.execute('UPDATE events SET details_json=? WHERE id=?',
                (json.dumps({'source': 'ep_patrol_local', 'PRIVATE': 'content'}), EVENT))
    else:
        with api.services.photos.db:
            api.services.photos.db.execute('UPDATE cloud_photos SET content=? WHERE key=?',
                (b'PRIVATE-BYTES' if damage == 'bytes' else b'PRIVATE' * 260000, photos[0]['path']))
    response = api.client.get(URL, headers=api.staff)
    assert response.status_code == 503 and b'PRIVATE' not in response.content
