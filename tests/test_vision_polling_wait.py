import threading
from types import SimpleNamespace

import pytest

from edge_hub import vision_runtime as module
from edge_hub.events import EventStore
from tools.acceptance_preflight import collect


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf', '-inf', '1e999', '1e-9999', 'private-invalid'])
def test_invalid_polling_interval_is_fixed_configuration_error(value):
    with pytest.raises(ValueError, match='^invalid vision polling interval$'):
        module.vision_frame_interval(value)


@pytest.mark.parametrize('value,seconds', [('300', .3), ('0.1', .0001), (' 1000 ', 1.), ('1e3', 1.)])
def test_valid_positive_finite_polling_interval(value, seconds):
    assert module.vision_frame_interval(value) == seconds


def test_interval_cannot_exceed_native_event_wait_limit():
    with pytest.raises(ValueError, match='polling interval'):
        module.vision_frame_interval(str(threading.TIMEOUT_MAX * 2000))


def test_preflight_rejects_nan_interval_without_devices_or_files(tmp_path, monkeypatch):
    monkeypatch.setenv('ZHIWEI_VISION_INTERVAL_MS', 'nan')
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *a: pytest.fail('device forbidden'))
    report = collect(tmp_path, offline=True)
    assert report['vision_configuration_error'] == 'ValueError'
    assert report['camera_opened'] is False and report['gates']['litter_report'] is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('scenario', ['read', 'uncalibrated', 'calibrate', 'storm', 'empty', 'privacy', 'processed'])
def test_every_worker_polling_wait_uses_stop_event(tmp_path, monkeypatch, scenario):
    store = EventStore()
    runtime = module.VisionRuntime(tmp_path, store, enabled=False)
    runtime.frame_interval = 3600.  # Fixture only: fake wait never sleeps or opens a device.
    waits, releases = [], []
    expected = ([.2] if scenario == 'read' else [3600.] if scenario == 'uncalibrated'
                else [.25] if scenario == 'calibrate' else [.25, 3600.])

    def wait(seconds):
        waits.append(seconds)
        if len(waits) >= len(expected):
            runtime._stop.set()
            return True
        return False

    def privacy(frame):
        if scenario == 'privacy':
            raise RuntimeError('fixture privacy failure')
        return []

    if scenario not in {'read', 'uncalibrated'}:
        runtime._calibrate.set()
    monkeypatch.setattr(runtime._stop, 'wait', wait)
    monkeypatch.setattr(module.time, 'sleep', lambda *a: pytest.fail('uninterruptible sleep forbidden'))
    camera = SimpleNamespace(isOpened=lambda: True, read=lambda: (scenario != 'read', object()),
                             release=lambda: releases.append(True))
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *a: camera)
    monkeypatch.setattr(module, 'OnnxCropClassifier', lambda *a: object())
    monkeypatch.setattr(module, 'PersonPrivacyDetector', lambda *a: SimpleNamespace(detect=privacy))
    monkeypatch.setattr(module, 'BackgroundCandidateDetector', lambda: SimpleNamespace(
        calibrate=lambda frame: None, scene_unstable=False,
        candidates=lambda frame: [] if scenario == 'empty' else [(0, 0, 1, 1)]))
    gate = SimpleNamespace(reset=lambda: None, update=lambda boxes: None)
    monkeypatch.setattr(module, 'LitterFrameProcessor', lambda *a: SimpleNamespace(
        gate=gate, detect=lambda *a: []))
    monkeypatch.setattr(module, 'PrivacyEvidenceWriter', lambda *a: object())
    monkeypatch.setattr(module, 'EventStormGuard', lambda: SimpleNamespace(
        tripped=scenario == 'storm', reset=lambda: None))
    try:
        runtime._run()
        assert waits == expected and releases == [True]
        assert runtime._stop.is_set() and runtime._status != 'failed'
        assert store.stats()['total'] == 0
    finally:
        store.close()
