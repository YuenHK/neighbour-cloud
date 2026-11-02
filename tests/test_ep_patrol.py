import hashlib
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from edge_hub.ep_patrol import EpPatrol, PatrolSettings, patrol_router
from edge_hub.events import Event, EventStore
from edge_hub.robot_control import ControlError
from ep_runtime.manual_warning import ManualWarning


def jpeg(color=80):
    ok, data = cv2.imencode('.jpg', np.full((360, 640, 3), color, dtype=np.uint8))
    assert ok
    return data.tobytes()


@pytest.fixture
def patrol(tmp_path):
    frame = {'state': 'frame', 'jpeg': jpeg(), 'key': 'epoch-1', 'sn': 'SYNTHETIC0930',
             'device_id': 'ep-2', 'captured_at_ms': int(time.time()*1000)}
    store = EventStore(tmp_path/'events.sqlite3')
    manager = EpPatrol(lambda device: dict(frame), store, tmp_path/'data',
                       observe=lambda data, restricted: {'litter', 'standing_water'}, background=False,
                       context_source=lambda device, anchor, cancelled: [
                           {'side': side, 'jpeg': jpeg(120+index),
                            'frame_key': anchor['key']+f'-{side}',
                            'captured_at_ms': anchor['captured_at_ms']+index+1,
                            'offset': 30 if side == 'left' else -30}
                           for index, side in enumerate(('left', 'right'))])
    yield manager, store, frame
    manager.close()
    store.close()


def step(manager, frame, sequence):
    frame['key'] = f'epoch-{sequence}'
    manager.states['ep-2']['next_at'] = 0
    manager.step('ep-2')


def test_durable_photo_delivery_survives_database_failure_and_restart(patrol, monkeypatch):
    manager, store, frame = patrol
    original = store.add
    monkeypatch.setattr(store, 'add', lambda event: (_ for _ in ()).throw(OSError('offline db')))
    manager.configure('ep-2', PatrolSettings(enabled=True))
    step(manager, frame, 1)
    step(manager, frame, 2)
    pending = list((manager.data_root/'events/ep-patrol').glob('*.pending.json'))
    assert len(pending) == 2 and not store.all()
    assert len(list(pending[0].parent.glob('*.jpg'))) == 6
    monkeypatch.setattr(store, 'add', original)
    restarted = EpPatrol(lambda _: pytest.fail('recovery must not access robot'), store,
                         manager.data_root, background=False)
    restarted.deliver_pending()
    restarted.deliver_pending()
    assert len(store.all()) == 2
    assert not list(pending[0].parent.glob('*.pending.json'))
    assert len(list(pending[0].parent.glob('*.jpg'))) == 6
    restarted.close()


def test_missing_side_photo_blocks_delivery(patrol):
    manager, store, frame = patrol
    manager.context_source = lambda *_: []
    manager.configure('ep-2', PatrolSettings(enabled=True))
    step(manager, frame, 1)
    step(manager, frame, 2)
    assert not store.all()
    assert manager.status('ep-2')['state'] == 'unavailable'


def test_each_pushed_candidate_has_the_exact_analyzed_ep_photo_and_source(patrol):
    manager, store, frame = patrol
    manager.configure('ep-2', PatrolSettings(enabled=True, zone='公開測試區'))
    step(manager, frame, 1)
    assert not store.all()
    frame['jpeg'] = jpeg(170)
    step(manager, frame, 2)
    events = store.all()
    assert {event.type for event in events} == {'litter_detected', 'leak_detected'}
    for event in events:
        assert event.status == 'pending' and event.details['review_required']
        assert (manager.data_root/event.evidence).read_bytes() == frame['jpeg']
        assert event.details['photo_sha256'] == hashlib.sha256(frame['jpeg']).hexdigest()
        assert event.details['frame_key'] == 'epoch-2' and event.details['robot_sn'] == 'SYNTHETIC0930'
    step(manager, frame, 3)
    assert len(store.all()) == 2  # Dedup without changing the original evidence.


def test_no_photo_no_report_and_late_result_after_disable_is_fenced(patrol):
    manager, store, frame = patrol
    manager.configure('ep-2', PatrolSettings(enabled=True))
    def disabled(data, restricted):
        manager.configure('ep-2', PatrolSettings(enabled=False))
        return {'smoke_flame'}
    manager.observe = disabled
    step(manager, frame, 1)
    assert not store.all()
    manager.configure('ep-2', PatrolSettings(enabled=True))
    manager.observe = lambda *_: {'smoke_flame'}
    frame['jpeg'] = b'not a photo'
    step(manager, frame, 2)
    assert not store.all() and manager.status('ep-2')['state'] == 'unavailable'


def test_people_in_normal_areas_never_generate_a_suspicion_report(patrol):
    manager, store, frame = patrol
    manager.observe = lambda *_: {'restricted_presence'}  # Untrusted model output is gated again.
    manager.configure('ep-2', PatrolSettings(enabled=True, restricted_area=False))
    step(manager, frame, 1)
    step(manager, frame, 2)
    assert not store.all()
    manager.configure('ep-2', PatrolSettings(enabled=True, restricted_area=True))
    step(manager, frame, 3)
    step(manager, frame, 4)
    event = store.all()[0]
    assert event.type == 'access_candidate' and '禁區' in event.details['caption']
    assert 'suspicious' not in str(event.details)


def test_smoke_candidate_never_operates_robot_and_disconnect_drops_late_results(patrol):
    manager, store, frame = patrol
    manager.configure('ep-2', PatrolSettings(enabled=True))
    def disconnect(data, restricted):
        frame['state'] = 'stale'
        return {'smoke_flame'}
    manager.observe = disconnect
    step(manager, frame, 1)
    assert not store.all()
    frame['state'] = 'frame'
    manager.observe = lambda *_: {'smoke_flame'}
    step(manager, frame, 2)
    assert store.all()[0].type == 'smoke_fire_candidate'


def test_new_video_epoch_cannot_confirm_old_observations(patrol):
    manager, store, frame = patrol
    manager.configure('ep-2', PatrolSettings(enabled=True))
    step(manager, frame, 1)
    frame['key'] = 'newvideo-1'
    manager.states['ep-2']['next_at'] = 0
    manager.step('ep-2')
    assert not store.all()


def test_private_snapshot_authentication_integrity_and_legacy_evidence_remain_strict(patrol):
    manager, store, frame = patrol
    manager.configure('ep-2', PatrolSettings(enabled=True))
    step(manager, frame, 1)
    step(manager, frame, 2)
    event = store.all()[0]
    def auth(key):
        if key != 'synthetic':
            raise HTTPException(403)
    app = FastAPI()
    app.include_router(patrol_router(manager, auth))
    with TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 1)) as client:
        url = '/api/v1/patrol/events/'+event.id+'/photo'
        assert client.get(url).status_code == 403
        assert client.get(url, headers={'X-Operator-Key': 'synthetic'}).content == frame['jpeg']
        assert client.get(url, headers={'X-Operator-Key': 'synthetic', 'Origin': 'https://outside.invalid'}).status_code == 403
        (manager.data_root/event.evidence).write_bytes(jpeg(30))
        assert client.get(url, headers={'X-Operator-Key': 'synthetic'}).status_code == 409
    with pytest.raises(ValueError):
        Event(id='x', type='litter_detected', zone='x', at_ms=1, severity='notice', evidence='events/unblurred.jpg')


def test_manual_warning_only_uses_led_and_one_notification_sound():
    calls = []
    action = SimpleNamespace(wait_for_completed=lambda **kw: calls.append(('wait', kw)), has_succeeded=True)
    robot = SimpleNamespace(led=SimpleNamespace(set_led=lambda **kw: calls.append(('led', kw)) or True),
                            blaster=SimpleNamespace(set_led=lambda **kw: calls.append(('trajectory', kw)) or True,
                                                    fire=lambda **kw: pytest.fail('firing is forbidden')),
                            play_sound=lambda **kw: calls.append(('sound', kw)) or action)
    warning = ManualWarning(duration=.001)
    assert warning.start(robot)['requested']
    warning.thread.join(timeout=1)
    assert warning.snapshot()['state'] == 'completed'
    assert [value for kind, value in calls if kind == 'sound'] == [{'sound_id': 0x104, 'times': 1}]
    assert len([value for kind, value in calls if kind == 'led']) == 2
    assert [value for kind, value in calls if kind == 'trajectory'] == [
        {'brightness': 255, 'effect': 'on'}, {'brightness': 0, 'effect': 'off'}]
    with pytest.raises(ControlError):
        warning.start(robot)
    with pytest.raises(ControlError):
        ManualWarning().start(None)


def test_trajectory_led_is_turned_off_when_sound_fails():
    calls = []
    def failed_sound(**kwargs):
        raise OSError('synthetic sound failure')
    robot = SimpleNamespace(led=SimpleNamespace(set_led=lambda **kw: True),
        blaster=SimpleNamespace(set_led=lambda **kw: calls.append(kw) or True,
                                fire=lambda **kw: pytest.fail('never fire')),
        play_sound=failed_sound)
    warning = ManualWarning(duration=.001)
    warning.start(robot)
    warning.thread.join(1)
    assert calls == [{'brightness': 255, 'effect': 'on'}, {'brightness': 0, 'effect': 'off'}]
    assert warning.snapshot()['state'] == 'unconfirmed'
