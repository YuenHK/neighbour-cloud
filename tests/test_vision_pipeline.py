from pathlib import Path

import numpy as np
import pytest

from edge_hub.vision import (
    BackgroundCandidateDetector,
    Detection,
    LitterFrameProcessor,
    OnnxObjectDetector,
    PrivacyEvidenceWriter,
    TemporalDetectionGate,
)
from tools.build_dataset_manifest import build_manifest


class FakeInput:
    name = "images"


class FakeSession:
    def get_inputs(self):
        return [FakeInput()]

    def run(self, _outputs, inputs):
        assert inputs["images"].shape == (1, 3, 320, 320)
        return [np.array([[32, 32, 160, 160, 0.9, 0]], dtype=np.float32)]


def test_onnx_contract_maps_detection_to_original_image() -> None:
    detector = OnnxObjectDetector(Path("unused.onnx"), session=FakeSession())

    detections = detector.detect(np.zeros((640, 640, 3), dtype=np.uint8))

    assert detections[0].label == "plastic_bottle"
    assert detections[0].box == (64, 64, 256, 256)


def test_litter_requires_three_consecutive_frames() -> None:
    gate = TemporalDetectionGate(required_frames=3, confidence_threshold=0.8)
    detection = Detection("aluminium_can", 0.9, (0, 0, 10, 10))

    assert gate.update([detection]) == []
    assert gate.update([detection]) == []
    assert gate.update([detection]) == [detection]
    assert gate.update([detection]) == []


def test_privacy_failure_never_writes_full_frame(tmp_path: Path) -> None:
    output = tmp_path / "data/events/evt-1-blurred.jpg"

    result = PrivacyEvidenceWriter().save(
        np.zeros((20, 20, 3), dtype=np.uint8), [], output, privacy_check_passed=False
    )

    assert result is None
    assert not output.exists()


@pytest.mark.parametrize("unverified", [None, "false", "true", 1, [], {}])
def test_evidence_requires_literal_privacy_confirmation(tmp_path, unverified):
    output = Path("data/events/evt-unverified-blurred.jpg")
    assert PrivacyEvidenceWriter(tmp_path).save(
        np.zeros((20, 20, 3), dtype=np.uint8), [], output,
        privacy_check_passed=unverified,
    ) is None
    assert not (tmp_path / output).exists()


def test_bad_mask_does_not_reach_image_writer(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid mask reached image persistence")
    monkeypatch.setattr("edge_hub.vision.cv2.imencode", forbidden)
    with pytest.raises(ValueError, match="privacy box"):
        PrivacyEvidenceWriter(tmp_path).save(
            np.zeros((20, 20, 3), dtype=np.uint8), [(0, 0, 0, 10)],
            Path("data/events/evt-invalid-blurred.jpg"), privacy_check_passed=True,
        )


def test_verified_evidence_writer_saves_masked_copy_only(tmp_path):
    import cv2

    pattern = ((np.indices((48, 48)).sum(axis=0) % 2) * 255).astype(np.uint8)
    image = np.repeat(pattern[..., None], 3, axis=2)
    original = image.copy()
    output = Path("data/events/evt-valid-blurred.jpg")
    assert PrivacyEvidenceWriter(tmp_path).save(
        image, [(0, 0, 48, 48)], output, privacy_check_passed=True,
    ) == output
    saved = cv2.imread(str(tmp_path / output))
    assert saved is not None and saved.shape == image.shape
    assert not np.array_equal(saved, original)
    assert np.array_equal(image, original)
    assert list((tmp_path / "data/events").iterdir()) == [tmp_path / output]


def test_manifest_splits_scenes_deterministically(tmp_path: Path) -> None:
    image = tmp_path / "plastic_bottle" / "corridor-a" / "frame-1.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"test")
    second_image = image.with_name("frame-2.jpg")
    second_image.write_bytes(b"test")

    first = build_manifest(tmp_path)
    second = build_manifest(tmp_path)

    assert first == second
    assert first["items"][0]["label"] == "plastic_bottle"
    assert first["items"][0]["scene"] == "corridor-a"
    assert first["items"][0]["split"] == first["items"][1]["split"]
    assert first["items"][0]["split"] in {"train", "validation", "test"}


class FakeClassifier:
    def classify(self, _crop):
        return "paper_cup", 0.95


def test_background_candidates_flow_through_three_frame_gate() -> None:
    background = np.zeros((100, 100, 3), dtype=np.uint8)
    frame = background.copy()
    frame[20:60, 30:70] = 255
    candidates = BackgroundCandidateDetector(minimum_area=100)
    candidates.calibrate(background)
    processor = LitterFrameProcessor(FakeClassifier(), candidates)

    assert processor.detect(frame) == []
    assert processor.detect(frame) == []
    confirmed = processor.detect(frame)

    assert confirmed[0].label == "paper_cup"
    assert confirmed[0].box[2] >= 40


def test_background_candidates_are_bounded_for_cpu_safety() -> None:
    background = np.zeros((240, 240, 3), dtype=np.uint8)
    frame = background.copy()
    for index in range(6):
        x = 10 + (index % 3) * 75
        y = 10 + (index // 3) * 110
        frame[y : y + 50, x : x + 50] = 255
    candidates = BackgroundCandidateDetector(minimum_area=100, max_candidates=4)
    candidates.calibrate(background)

    assert len(candidates.candidates(frame)) == 4
