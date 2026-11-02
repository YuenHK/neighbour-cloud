from types import SimpleNamespace

import pytest

from edge_hub import vision_runtime as module
from edge_hub.events import EventStore


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    store = EventStore()
    runtime = module.VisionRuntime(tmp_path, store, enabled=False)
    monkeypatch.setattr(runtime, '_model_accepted', lambda: False)
    monkeypatch.setattr(runtime, '_privacy_accepted', lambda: False)
    try:
        yield runtime
    finally:
        store.close()


def test_unobserved_frame_is_unknown_not_zero_or_running_proof(runtime):
    report = runtime.status()
    assert report['last_frame_age_ms'] is None
    assert report['poll_interval_ms'] == 300.
    assert 'not image quality' in report['frame_observation_scope']
    assert report['raw_frames_saved'] == 0 and report['enabled'] is False


def test_frame_age_uses_monotonic_clock_and_does_not_change_state(runtime, monkeypatch):
    runtime._last_frame_tick = 10.
    runtime._status = 'failed'
    monkeypatch.setattr(module.time, 'monotonic', lambda: 12.3456)
    monkeypatch.setattr(module.time, 'time', lambda: pytest.fail('wall clock forbidden'))
    assert runtime.status()['last_frame_age_ms'] == 2345.6
    assert runtime.status()['status'] == 'failed'
    monkeypatch.setattr(module.time, 'monotonic', lambda: 9.)
    assert runtime.status()['last_frame_age_ms'] == 0.


@pytest.mark.parametrize('read_result', ['success', 'failure', 'stopped'])
def test_only_successful_non_discarded_read_updates_observation(runtime, monkeypatch, read_result):
    releases = []

    def read():
        if read_result == 'stopped':
            runtime._stop.set()
        return read_result != 'failure', object()

    def wait(seconds):
        runtime._stop.set()
        return True

    monkeypatch.setattr(module.time, 'monotonic', lambda: 100.)
    monkeypatch.setattr(runtime._stop, 'wait', wait)
    camera = SimpleNamespace(isOpened=lambda: True, read=read, release=lambda: releases.append(True))
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *a: camera)
    for name in ('OnnxCropClassifier', 'PersonPrivacyDetector', 'BackgroundCandidateDetector',
                 'LitterFrameProcessor', 'PrivacyEvidenceWriter'):
        monkeypatch.setattr(module, name, lambda *a: object())
    runtime._run()  # Fake read then calibration wait only; no real device, frames or models.
    assert runtime._last_frame_tick == (100. if read_result == 'success' else None)
    assert releases == [True] and runtime.store.stats()['total'] == 0


def test_new_worker_attempt_resets_age_but_live_worker_does_not(runtime, tmp_path, monkeypatch):
    runtime.person_model = tmp_path / 'fake.onnx'
    runtime.person_model.write_bytes(b'fixture only')
    monkeypatch.setattr(runtime, '_model_accepted', lambda: True)
    monkeypatch.setattr(runtime, '_privacy_accepted', lambda: True)
    worker = SimpleNamespace(start=lambda: None, is_alive=lambda: False)
    monkeypatch.setattr(module.threading, 'Thread', lambda **kwargs: worker)
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *a: pytest.fail('device forbidden'))
    runtime._last_frame_tick = 10.
    runtime.enable()
    assert runtime._last_frame_tick is None
    worker.is_alive = lambda: True
    runtime._last_frame_tick = 20.
    runtime.enable()
    assert runtime._last_frame_tick == 20.
