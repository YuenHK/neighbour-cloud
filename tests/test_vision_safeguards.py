from pathlib import Path

import numpy as np
import pytest

from edge_hub.privacy import safe_evidence_path
from edge_hub.vision import (
    BackgroundCandidateDetector,
    Detection,
    EventStormGuard,
    LitterFrameProcessor,
    TemporalDetectionGate,
)


def detection(label='paper_cup', x=0):
    return Detection(label, 0.95, (x, 0, 20, 20))


def test_same_object_not_reannounced_after_brief_miss_or_label_flicker():
    gate = TemporalDetectionGate(rearm_frames=10)
    for _ in range(2):
        assert gate.update([detection()]) == []
    assert gate.update([detection()])
    for _ in range(100):
        gate.update([])
        assert gate.update([detection('aluminium_can')]) == []
        assert gate.update([detection()]) == []


def test_rearm_requires_ten_absent_frames():
    gate = TemporalDetectionGate()
    for _ in range(3):
        gate.update([detection()])
    for _ in range(10):
        gate.update([])
    assert gate.update([detection()]) == []
    assert gate.update([detection()]) == []
    assert gate.update([detection()])


def test_same_label_in_different_positions_cannot_accumulate_confirmation():
    gate = TemporalDetectionGate()
    assert gate.update([detection(x=0)]) == []
    assert gate.update([detection(x=100)]) == []
    assert gate.update([detection(x=200)]) == []


def test_two_separate_objects_of_same_class_are_both_confirmed():
    gate = TemporalDetectionGate()
    for _ in range(2):
        assert gate.update([detection(x=0), detection(x=100)]) == []
    assert len(gate.update([detection(x=0), detection(x=100)])) == 2


def test_lighting_change_and_large_scene_change_do_not_create_candidates():
    baseline = np.full((100, 100, 3), 60, dtype=np.uint8)
    detector = BackgroundCandidateDetector(minimum_area=50)
    detector.calibrate(baseline)
    assert detector.candidates(baseline + 40) == []
    moved = baseline.copy()
    moved[:50] = 200
    assert detector.candidates(moved) == []
    assert detector.scene_unstable


def test_person_overlap_is_not_classified_as_trash():
    class Classifier:
        def classify(self, _):
            raise AssertionError('person must be screened before classification')
    baseline = np.zeros((100, 100, 3), dtype=np.uint8)
    frame = baseline.copy()
    frame[20:60, 20:60] = 255
    detector = BackgroundCandidateDetector(minimum_area=100)
    detector.calibrate(baseline)
    processor = LitterFrameProcessor(Classifier(), detector)
    assert processor.detect(frame, [(10, 10, 60, 70)]) == []


def test_evidence_traversal_is_rejected():
    with pytest.raises(ValueError):
        safe_evidence_path(Path('data/events/../../unsafe-blurred.jpg'))


def test_event_storm_is_bounded_and_cannot_automatically_resume():
    now = [0.0]
    guard = EventStormGuard(clock=lambda: now[0])
    assert all(guard.allow() for _ in range(6))
    assert not guard.allow()
    now[0] = 100
    assert not guard.allow()
    guard.reset()
    assert guard.allow()


def test_sensor_noise_does_not_become_foreground_but_real_object_remains():
    rng = np.random.default_rng(42)
    background = np.full((240, 320, 3), 90, dtype=np.uint8)
    detector = BackgroundCandidateDetector()
    detector.calibrate(background)
    noisy = np.clip(background.astype(float) + rng.normal(0, 18, background.shape), 0, 255).astype(np.uint8)
    assert detector.candidates(noisy) == []
    noisy[60:140, 100:160] = 220
    assert detector.candidates(noisy)
