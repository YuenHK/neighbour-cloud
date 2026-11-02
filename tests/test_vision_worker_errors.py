import json
from types import SimpleNamespace

import pytest

from edge_hub.events import EventStore
from edge_hub.vision_runtime import VisionRuntime


class PrivateFailure(Exception):
    def __str__(self):
        raise AssertionError('must not format PRIVATE_EXCEPTION_CONTENT')


@pytest.fixture
def worker(tmp_path, monkeypatch):
    from edge_hub import vision_runtime as module

    store = EventStore()
    runtime = VisionRuntime(tmp_path, store, enabled=False)
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(module, 'OnnxCropClassifier', lambda path: object())
    monkeypatch.setattr(module, 'PersonPrivacyDetector', lambda path: object())
    monkeypatch.setattr(module, 'BackgroundCandidateDetector', lambda: object())
    monkeypatch.setattr(module, 'LitterFrameProcessor', lambda *args: object())
    monkeypatch.setattr(module, 'PrivacyEvidenceWriter', lambda path: object())
    try:
        yield module, runtime, store
    finally:
        store.close()


class FakeCamera:
    def __init__(self, failure=None, opened=True):
        self.failure, self.opened, self.releases = failure, opened, 0

    def isOpened(self):
        if self.failure == 'open':
            raise PrivateFailure()
        return self.opened

    def read(self):
        if self.failure == 'read':
            raise PrivateFailure()
        return True, object()

    def release(self):
        self.releases += 1
        if self.failure == 'release':
            raise PrivateFailure()


def assert_safe_status(runtime, store, error):
    status = runtime.status()
    assert status['error'] == error
    assert status['events_created'] == 0 and status['raw_frames_saved'] == 0
    assert 'PrivateFailure' not in json.dumps(status)
    assert 'PRIVATE_EXCEPTION_CONTENT' not in json.dumps(status)
    assert runtime.enabled is False and runtime._thread is None
    assert store.stats()['total'] == 0


@pytest.mark.parametrize('failure', ['construct', 'open', 'classifier', 'read', 'release'])
def test_worker_failure_is_fixed_and_owned_camera_is_released(worker, monkeypatch, failure):
    module, runtime, store = worker
    camera = FakeCamera(failure=failure)
    def capture(*args):
        if failure == 'construct':
            raise PrivateFailure()
        return camera
    monkeypatch.setattr(module.cv2, 'VideoCapture', capture)
    if failure == 'classifier':
        def classifier(path):
            raise PrivateFailure()
        monkeypatch.setattr(module, 'OnnxCropClassifier', classifier)
    if failure == 'release':
        def read_then_stop():
            runtime._stop.set()
            return True, object()
        monkeypatch.setattr(camera, 'read', read_then_stop)
    runtime._run()  # Fake capture only; never start()/enable() or a real device.
    assert runtime._status == 'failed'
    expected = ('camera initialization failed' if failure in {'construct', 'open'} else
                'camera release failed' if failure == 'release' else 'vision pipeline failed')
    assert_safe_status(runtime, store, expected)
    assert camera.releases == (0 if failure == 'construct' else 1)


def test_unavailable_camera_releases_once_without_loading_models(worker, monkeypatch):
    module, runtime, store = worker
    camera = FakeCamera(opened=False)
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *args: camera)
    monkeypatch.setattr(module, 'OnnxCropClassifier', lambda path: pytest.fail('must not load model'))
    runtime._run()
    assert runtime._status == 'camera_unavailable' and camera.releases == 1
    assert_safe_status(runtime, store, 'camera unavailable')


def test_privacy_error_never_classifies_saves_or_creates_event(worker, monkeypatch):
    module, runtime, store = worker
    camera = FakeCamera()
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *args: camera)
    runtime._calibrate.set()
    candidates = SimpleNamespace(calibrate=lambda frame: None, candidates=lambda frame: [object()])
    processor = SimpleNamespace(
        gate=SimpleNamespace(reset=lambda: None, update=lambda boxes: None),
        detect=lambda *args: pytest.fail('privacy failure must block classification'))
    def detect(frame):
        runtime._stop.set()
        raise PrivateFailure()
    monkeypatch.setattr(module, 'BackgroundCandidateDetector', lambda: candidates)
    monkeypatch.setattr(module, 'LitterFrameProcessor', lambda *args: processor)
    monkeypatch.setattr(module, 'PersonPrivacyDetector', lambda path: SimpleNamespace(detect=detect))
    monkeypatch.setattr(module, 'PrivacyEvidenceWriter', lambda path: SimpleNamespace(
        save=lambda *a, **kw: pytest.fail('privacy failure must block evidence')))
    runtime._run()
    assert runtime._status == 'privacy_unavailable' and camera.releases == 1
    assert_safe_status(runtime, store, 'privacy detector failed')


def test_stop_requested_during_read_drops_returned_frame_before_processing(worker, monkeypatch):
    module, runtime, store = worker
    camera = FakeCamera()
    def read():
        runtime.disable()
        return True, object()
    monkeypatch.setattr(camera, 'read', read)
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *args: camera)
    # The fixture processor/candidates have no processing methods: any use fails the test.
    runtime._run()
    assert runtime.status()['status'] == 'disabled'
    assert runtime.status()['stop_requested'] is True
    assert runtime._frames == 0 and camera.releases == 1
    assert store.stats()['total'] == 0


def test_delayed_worker_with_stop_already_requested_never_opens_device(worker, monkeypatch):
    module, runtime, store = worker
    runtime.disable()
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *a: pytest.fail('must not open after stop'))
    runtime._run()
    assert runtime.status()['status'] == 'disabled'
    assert store.stats()['total'] == 0


@pytest.mark.parametrize('stage', ['open', 'classifier', 'privacy'])
def test_stop_during_initialization_skips_remaining_model_setup(worker, monkeypatch, stage):
    module, runtime, store = worker
    camera = FakeCamera()
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *a: camera)
    if stage == 'open':
        def opened():
            runtime.disable()
            return True
        monkeypatch.setattr(camera, 'isOpened', opened)
        monkeypatch.setattr(module, 'OnnxCropClassifier', lambda *a: pytest.fail('must skip classifier'))
    elif stage == 'classifier':
        def classifier(path):
            runtime.disable()
            return object()
        monkeypatch.setattr(module, 'OnnxCropClassifier', classifier)
    if stage == 'privacy':
        def privacy(path):
            runtime.disable()
            return object()
        monkeypatch.setattr(module, 'PersonPrivacyDetector', privacy)
    else:
        monkeypatch.setattr(module, 'PersonPrivacyDetector', lambda *a: pytest.fail('must skip privacy setup'))
    monkeypatch.setattr(module, 'BackgroundCandidateDetector', lambda: pytest.fail('must skip candidate setup'))
    runtime._run()
    assert camera.releases == 1 and runtime.status()['status'] == 'disabled'
    assert store.stats()['total'] == 0


@pytest.mark.parametrize('stage', ['calibration', 'candidates', 'privacy', 'classification', 'evidence', 'event'])
def test_stop_between_processing_stages_never_starts_the_next_stage(worker, monkeypatch, stage):
    module, runtime, store = worker
    camera = FakeCamera()
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *a: camera)
    runtime._calibrate.set()
    calls = []
    def reached(name):
        assert not runtime._stop.is_set(), 'must not enter a later stage after stop'
        calls.append(name)
        if stage == name:
            runtime.disable()
    def calibrate(frame):
        reached('calibration')
    def candidates(frame):
        reached('candidates')
        return [object()]
    def privacy(frame):
        reached('privacy')
        return []
    def classify(*args):
        reached('classification')
        return [SimpleNamespace(label='plastic_bottle', confidence=.9)] * 2
    def save(*args, **kwargs):
        # Implicit None: no image file is created by this fixture.
        reached('evidence')
    if stage == 'event':
        store.subscribe(lambda event: reached('event'))
    monkeypatch.setattr(module, 'BackgroundCandidateDetector', lambda: SimpleNamespace(
        calibrate=calibrate, candidates=candidates, scene_unstable=False))
    monkeypatch.setattr(module, 'PersonPrivacyDetector', lambda path: SimpleNamespace(detect=privacy))
    monkeypatch.setattr(module, 'LitterFrameProcessor', lambda *args: SimpleNamespace(
        gate=SimpleNamespace(reset=lambda: None, update=lambda boxes: None), detect=classify))
    monkeypatch.setattr(module, 'PrivacyEvidenceWriter', lambda path: SimpleNamespace(save=save))
    runtime._run()
    assert calls[-1] == stage
    expected = 1 if stage == 'event' else 0
    assert store.stats()['total'] == runtime._events == expected
    assert calls.count('evidence') <= 1  # A committed first event cannot trigger a second write.
    assert camera.releases == 1 and runtime.status()['status'] == 'disabled'
