import base64
import hashlib
import io
import json
import sqlite3
import time
from types import SimpleNamespace

import httpx
import pytest
import test_cloud_bootstrap
import test_cloud_google_identity
from cryptography.exceptions import InvalidTag
from PIL import Image

from deploy.cloud.bootstrap import open_services
from deploy.cloud.operations import Operations, migrate
from deploy.cloud.patrol_ingest import PatrolIngest
from deploy.cloud.staff_push import StaffPush, valid_subscription
from edge_hub.events import Event
from edge_hub.patrol_delivery import PatrolDelivery
from edge_hub.service_desk import ResidentCase

prepared = test_cloud_bootstrap.prepared
seeded = test_cloud_bootstrap.seeded
keys = test_cloud_google_identity.keys


@pytest.fixture
def system(seeded):
    profile = seeded[0]
    services = open_services(profile, signing_key_loader=lambda: test_cloud_bootstrap.KEY)
    db = profile.connect(str(services.estate.path), check_same_thread=False)
    migrate(db)
    ops = Operations(db, test_cloud_bootstrap.KEY)
    try:
        yield SimpleNamespace(services=services, ops=ops, ingest=PatrolIngest(services, ops), db=db)
    finally:
        db.close()
        services.close()


def payload(root=None):
    photos, images = [], {}
    for index, side in enumerate(('event', 'left', 'right')):
        buffer = io.BytesIO()
        Image.new('RGB', (16, 16), ('red', 'green', 'blue')[index]).save(buffer, format='JPEG')
        raw = buffer.getvalue()
        path = f'events/ep-patrol/{index:032x}.jpg'
        photos.append({'side': side, 'path': path, 'sha256': hashlib.sha256(raw).hexdigest(), 'frame_key': 'session-' + side})
        images[side] = base64.b64encode(raw).decode()
        if root:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    event = Event(id='f'*32, type='leak_detected', zone='PUBLIC SYNTHETIC', at_ms=int(time.time()*1000),
        severity='notice', evidence=photos[0]['path'], details={'source': 'ep_patrol_local', 'review_required': True,
        'robot_sn': 'SYNTHETIC', 'frame_key': photos[0]['frame_key'], 'photo_sha256': photos[0]['sha256'],
        'photos': photos, 'caption': '公開合成候選，待核實。'})
    return {'event': event.model_dump(), 'images': images}


def test_no_implicit_schema_or_secret_plaintext():
    db = sqlite3.connect(':memory:', check_same_thread=False)
    with pytest.raises(sqlite3.OperationalError):
        Operations(db, b'x'*32)
    migrate(db)
    ops = Operations(db, b'x'*32)
    sealed = ops.seal('test', 'one', {'secret': 'PRIVATE-CAPABILITY'})
    ops.put('test', 'one', {'sealed': sealed})
    assert 'PRIVATE-CAPABILITY' not in db.execute('SELECT payload FROM cloud_operations').fetchone()[0]
    assert ops.open('test', 'one', sealed)['secret'] == 'PRIVATE-CAPABILITY'
    with pytest.raises(InvalidTag):
        ops.open('test', 'other', sealed)


def test_patrol_three_photos_single_case_replay_and_conflict(system):
    pair = system.ingest.pair()
    assert system.ingest.identity(pair['token']) == pair['site']
    assert system.ingest.identity('invalid-token'*4) is None
    item = payload()
    before = system.services.cases.summary()
    receipt = system.ingest.accept(pair['site'], item)
    assert receipt['delivered'] and receipt['case_number'] == 2
    assert system.ingest.accept(pair['site'], item) == receipt
    assert system.services.cases.summary()['counts']['new'] == before['counts']['new'] + 1
    assert len(system.services.photos.db.execute('SELECT key FROM cloud_photos').fetchall()) == 3
    assert 'PUBLIC SYNTHETIC' not in repr(system.ops.items('patrol-receipt'))
    item['event']['zone'] = 'changed'
    with pytest.raises(ValueError, match='identity_conflict'):
        system.ingest.accept(pair['site'], item)


@pytest.mark.parametrize('phase', ['photo', 'case', 'receipt'])
def test_partial_effect_recovers_after_restart_without_duplicate(system, monkeypatch, phase):
    site = system.ingest.pair()['site']
    item = payload()
    if phase == 'photo':
        target, name = system.services.photos, 'put'
    elif phase == 'case':
        target, name = system.ingest.followup, 'ensure'
    else:
        target, name = system.ops, 'put'
    original = getattr(target, name)
    count = 0
    def failed(*args, **kwargs):
        nonlocal count
        count += 1
        if count == (2 if phase == 'receipt' else 1):
            raise OSError('synthetic lost acknowledgement')
        return original(*args, **kwargs)
    monkeypatch.setattr(target, name, failed)
    with pytest.raises(OSError):
        system.ingest.accept(site, item)
    monkeypatch.setattr(target, name, original)
    reopened = PatrolIngest(system.services, system.ops)
    assert reopened.accept(site, item)['case_number'] == 2
    assert reopened.accept(site, item)['case_number'] == 2
    assert system.services.cases.summary()['counts']['new'] == 2


def test_offline_and_unknown_response_outbox_reuses_identity(system, tmp_path):
    pair = system.ingest.pair()
    item = payload(tmp_path)
    count, now = 0, [0]
    def route(request):
        nonlocal count
        count += 1
        receipt = system.ingest.accept(pair['site'], json.loads(request.content))
        if count == 1:
            raise httpx.ReadTimeout('lost after commit')
        return httpx.Response(200, json=receipt)
    client = httpx.Client(transport=httpx.MockTransport(route))
    adapter = PatrolDelivery(tmp_path, 'https://neighbour-yuenhk-live.onrender.com',
                             {'site': pair['site'], 'token': pair['token']}, client=client, clock=lambda: now[0])
    event = Event.model_validate(item['event'])
    with pytest.raises(RuntimeError):
        adapter.add(event)
    with pytest.raises(RuntimeError, match='backoff'):
        adapter.add(event)
    assert count == 1
    now[0] = 100
    adapter.add(event)
    assert count == 2 and system.services.cases.summary()['counts']['new'] == 2
    assert (tmp_path / f'events/ep-patrol/{event.id}.receipt.json').is_file()


def test_outbox_backoff_survives_process_restart_after_lost_cloud_ack(system, tmp_path):
    pair, now, calls = system.ingest.pair(), [1000], []
    item = payload(tmp_path)
    def route(request):
        calls.append(request)
        receipt = system.ingest.accept(pair['site'], json.loads(request.content))
        if len(calls) == 1:
            raise httpx.ReadTimeout('synthetic response lost after commit')
        return httpx.Response(200, json=receipt)
    client = httpx.Client(transport=httpx.MockTransport(route))
    def adapter():
        return PatrolDelivery(tmp_path, 'https://neighbour-yuenhk-live.onrender.com',
                              {'site': pair['site'], 'token': pair['token']}, client=client, clock=lambda: now[0])
    event = Event.model_validate(item['event'])
    with pytest.raises(RuntimeError, match='unconfirmed'):
        adapter().add(event)
    restarted = adapter()
    with pytest.raises(RuntimeError, match='backoff'):
        restarted.add(event)
    assert len(calls) == 1
    now[0] += 301
    restarted.add(event)
    assert len(calls) == 2 and system.services.cases.summary()['counts']['new'] == 2
    assert not list(tmp_path.rglob('*.retry.json'))
    assert len(list(tmp_path.rglob('*.jpg'))) == 3


def test_outbox_retry_corruption_retains_all_evidence_and_does_not_transmit(system, tmp_path):
    pair = system.ingest.pair()
    item = payload(tmp_path)
    event = Event.model_validate(item['event'])
    state = tmp_path / f'events/ep-patrol/{event.id}.retry.json'
    state.write_text('{"event":"wrong"}')
    client = httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail('must not transmit')))
    adapter = PatrolDelivery(tmp_path, 'https://neighbour-yuenhk-live.onrender.com',
        {'site': pair['site'], 'token': pair['token']}, client=client)
    with pytest.raises(ValueError, match='invalid_outbox_retry_state'):
        adapter.add(event)
    assert len(list(tmp_path.rglob('*.jpg'))) == 3 and state.read_text() == '{"event":"wrong"}'


def subscription():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,
          serialization.PublicFormat.UncompressedPoint)
    return {'endpoint': 'https://fcm.googleapis.com/fcm/send/synthetic-only', 'keys': {
        'auth': base64.urlsafe_b64encode(b'x'*16).decode(), 'p256dh': base64.urlsafe_b64encode(key).decode()}}


def test_push_generic_cursor_and_encrypted_subscription_retry_then_remove(system):
    statuses, calls, now = [503, 201, 410], [], [100]
    def sender(sub, private, origin, notification_id, test):
        calls.append((sub, private, origin, notification_id, test))
        return statuses.pop(0)
    push = StaffPush(system.ops, system.services.cases, 'https://neighbour.example', sender=sender, clock=lambda: now[0])
    sub = subscription()
    push.subscribe(sub)
    push.tick()
    assert not calls  # No historical notification.
    system.services.cases.create(ResidentCase(submission_id='b'*32, kind='water', message='PRIVATE', confirmed=True))
    push.tick(); push.tick()
    assert len(calls) == 1
    now[0] = 200
    push.tick(); push.tick()
    assert len(calls) == 2
    assert calls[0][3] == calls[1][3] and len(calls[0][3]) == 64
    stored = repr(system.ops.items('push-subscription'))
    assert 'fcm.googleapis.com' not in stored and sub['keys']['auth'] not in stored
    system.services.cases.create(ResidentCase(submission_id='c'*32, kind='water', message='OTHER PRIVATE', confirmed=True))
    push.tick()
    assert len(calls) == 3 and system.ops.items('push-subscription') == []


def test_manual_push_test_is_durable_limited_and_does_not_consume_case_progress(system):
    calls, now = [], [100]
    push = StaffPush(system.ops, system.services.cases, 'https://neighbour.example',
        sender=lambda *args: calls.append(args) or 201, clock=lambda: now[0])
    identity = push.subscribe(subscription())
    before = system.ops.get('push-subscription', identity)
    cases = system.services.cases.summary()
    result = push.test_subscription(identity)
    assert result['accepted'] and result['device_delivery_confirmed'] is False
    assert len(calls) == 1 and system.services.cases.summary() == cases
    after = system.ops.get('push-subscription', identity)
    assert all(before[key] == after[key] for key in ('cursor', 'updated', 'next', 'failures', 'sealed'))
    system.services.cases.create(ResidentCase(submission_id='d'*32, kind='water', message='SYNTHETIC PENDING', confirmed=True))
    reopened = StaffPush(system.ops, system.services.cases, 'https://neighbour.example',
        sender=lambda *_: pytest.fail('must not retry'), clock=lambda: now[0])
    assert reopened.test_subscription(identity)['state'] == 'cooldown'
    status = reopened.subscription_status(identity)
    assert status['test_retry_after_seconds'] == 60 and 'sealed' not in status
    assert len(calls) == 1
    # A browser reconnect must not reset the server cooldown.
    push.subscribe(subscription_same := subscription())
    other = hashlib.sha256(subscription_same['endpoint'].encode()).hexdigest()
    assert other == identity and push.test_subscription(identity)['state'] == 'cooldown'
    assert system.ops.get('push-subscription', identity)['cursor'] == before['cursor']
    now[0] += 61
    assert push.test_subscription(identity)['accepted'] and len(calls) == 2
    push.tick()
    assert len(calls) == 3 and calls[-1][-1] is False  # Pending normal work was not skipped.


def test_manual_push_test_unknown_response_is_not_retried_and_expired_subscription_removed(system):
    now = [100]
    def failed(*_):
        raise OSError('synthetic capability not to expose')
    push = StaffPush(system.ops, system.services.cases, 'https://neighbour.example',
                     sender=failed, clock=lambda: now[0])
    identity = push.subscribe(subscription())
    assert push.test_subscription(identity)['state'] == 'not_accepted'
    assert push.test_subscription(identity)['state'] == 'cooldown'
    now[0] += 61
    push.sender = lambda *_: 410
    assert push.test_subscription(identity)['state'] == 'expired'
    assert push.subscription_status(identity) == {'registered': False}
    assert push.test_subscription(identity)['state'] == 'not_registered'


@pytest.mark.parametrize('endpoint', ['http://fcm.googleapis.com/a', 'https://127.0.0.1/a',
    'https://fcm.googleapis.com.evil.test/a', 'https://fcm.googleapis.com:8888/a', 'https://user@fcm.googleapis.com/a'])
def test_push_rejects_untrusted_destination(endpoint):
    sub = subscription()
    sub['endpoint'] = endpoint
    with pytest.raises(ValueError):
        valid_subscription(sub)


def test_machine_capability_is_ingest_only_and_staff_push_is_private(system, keys):
    from fastapi.testclient import TestClient

    from deploy.cloud.google_identity import GoogleIdentityVerifier
    from deploy.cloud.http_app import create_app
    origin = 'https://neighbour.example'
    identity_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,
                        json={'keys': [keys[1]]}, headers={'cache-control': 'max-age=300'})))
    verifier = GoogleIdentityVerifier(test_cloud_google_identity.CLIENT,
        {'staff-subject': 'staff', 'resident-subject': 'resident'}, client=identity_client)
    staff = {'Authorization': 'Bearer ' + test_cloud_google_identity.token(keys), 'Origin': origin}
    resident = {'Authorization': 'Bearer ' + test_cloud_google_identity.token(keys, sub='resident-subject'), 'Origin': origin}
    app = create_app(system.services, verifier, origin=origin, operations=system.ops)
    with TestClient(app, base_url=origin) as client:
        route = '/api/v1/service-desk/patrol-site'
        assert client.post(route, headers=resident).status_code == 403
        pair = client.post(route, headers=staff).json()
        token = {'Authorization': 'Bearer ' + pair['token'], 'Origin': origin}
        assert client.get('/api/v1/service-desk/requests', headers=token).status_code == 401
        assert client.post('/api/v1/robot/ep/connect', headers=token, json={}).status_code == 401
        assert client.post('/api/v1/patrol/delivery', headers=staff, json=payload()).status_code == 403
        assert client.post('/api/v1/patrol/delivery', headers={'Authorization': token['Authorization']}, json=payload()).status_code == 403
        item = payload()
        result = client.post('/api/v1/patrol/delivery', headers=token, json=item)
        assert result.status_code == 200 and result.json()['case_number'] == 2
        receipt = client.get('/api/v1/patrol/delivery/' + item['event']['id'], headers=token)
        assert receipt.status_code == 200 and receipt.json()['completed_ms'] is None
        assert client.get('/api/v1/service-desk/notifications', headers=resident).status_code == 403
        assert client.get('/api/v1/service-desk/notifications', headers=staff).json()['public_key']
        status_path = '/api/v1/service-desk/notifications/' + 'a'*64
        assert client.get(status_path + '/status', headers=resident).status_code == 403
        assert client.post(status_path + '/test', headers=resident).status_code == 403
        assert client.post(status_path + '/test').status_code == 403  # Missing same-origin proof.
        assert client.post(status_path + '/test', headers={'Origin': origin}).status_code == 401
        assert client.get(status_path + '/status', headers=staff).json() == {'registered': False}
        assert client.post(status_path + '/test', headers=staff).json()['state'] == 'not_registered'
        assert client.post('/api/v1/service-desk/notifications/invalid/test', headers=staff).status_code == 422
        assert client.post('/api/v1/patrol/delivery', headers=token, content=b'x'*1_450_001).status_code == 413


def test_sender_uses_in_memory_vapid_and_generic_payload_without_redirect(monkeypatch):
    import pywebpush
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from deploy.cloud.staff_push import send_push
    private = ec.generate_private_key(ec.SECP256R1()).private_bytes(serialization.Encoding.PEM,
              serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    calls = []
    def fake(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=201)
    monkeypatch.setattr(pywebpush, 'webpush', fake)
    assert send_push(subscription(), private, 'https://neighbour.example', 'a'*64) == 201
    assert json.loads(calls[0]['data']) == {'type': 'staff-update', 'notification_id': 'a'*64}
    assert calls[0]['timeout'] == 8 and calls[0]['ttl'] == 300


def test_fake_patrol_outbox_cloud_staff_progress_and_90day_local_evidence(system, tmp_path):
    from edge_hub.ep_patrol import EpPatrol, PatrolSettings
    from edge_hub.service_desk import ReviewCase
    pair = system.ingest.pair()
    def route(request):
        if request.method == 'POST':
            return httpx.Response(200, json=system.ingest.accept(pair['site'], json.loads(request.content)))
        event_id = request.url.path.rsplit('/', 1)[1]
        receipt = system.ops.get('patrol-receipt', pair['site'] + ':' + event_id)
        return httpx.Response(200, json={**receipt, 'completed_ms': int(time.time()*1000)-91*86400000})
    client = httpx.Client(transport=httpx.MockTransport(route))
    adapter = PatrolDelivery(tmp_path, 'https://neighbour-yuenhk-live.onrender.com',
                             {'site': pair['site'], 'token': pair['token']}, client=client)
    def jpeg(color):
        buffer = io.BytesIO()
        Image.new('RGB', (640, 360), color).save(buffer, format='JPEG')
        return buffer.getvalue()
    frame = {'state': 'frame', 'jpeg': jpeg('gray'), 'key': 'epoch-1', 'sn': 'SYNTHETIC', 'captured_at_ms': int(time.time()*1000)}
    manager = EpPatrol(lambda _: frame, adapter, tmp_path, lambda *_: {'standing_water'}, background=False,
        context_source=lambda _, anchor, cancelled: [{'side': side, 'jpeg': jpeg(color),
            'frame_key': 'epoch-' + side, 'captured_at_ms': anchor['captured_at_ms'] + index + 1}
            for index, (side, color) in enumerate((('left', 'blue'), ('right', 'green')))])
    manager.configure('synthetic-device', PatrolSettings(enabled=True, zone='SYNTHETIC'))
    manager.step('synthetic-device')
    frame['key'] = 'epoch-2'
    manager.states['synthetic-device']['next_at'] = 0
    manager.step('synthetic-device')
    manager.close()
    assert not list(tmp_path.rglob('*.pending.json'))
    assert len(list(tmp_path.rglob('*.jpg'))) == 3
    event = next(event for event in system.services.events.all() if event.details.get('source') == 'ep_patrol_local')
    linked = system.ingest.followup._link(event.id)
    system.services.cases.review(linked['case_id'], ReviewCase(expected_revision=1, status='acknowledged', note='已安排職員核實'))
    assert '已安排職員核實' in json.dumps(system.services.cases.progress('2'), ensure_ascii=False)
    assert system.services.events.get_event(event.id).status == 'confirmed'
    adapter.maintenance()
    assert not list(tmp_path.rglob('*.jpg'))
    assert json.loads(next(tmp_path.rglob('*.receipt.json')).read_text())['local_erased'] is True
    assert system.services.cases.summary()['counts'] == {'acknowledged': 1, 'new': 1}
