from pathlib import Path

import numpy as np
import pytest

from edge_hub.privacy import PersonPrivacyDetector, blur_boxes, safe_evidence_path


def test_blur_changes_only_target_region() -> None:
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    pattern = ((np.indices((10, 10)).sum(axis=0) % 2) * 255).astype(np.uint8)
    image[5:15, 5:15] = pattern[..., None]
    result = blur_boxes(image, [(5, 5, 10, 10)])
    assert not np.array_equal(result[5:15, 5:15], image[5:15, 5:15])
    assert np.array_equal(result[:5], image[:5])


def test_raw_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="blurred"):
        safe_evidence_path(Path("data/raw/frame.jpg"))


def test_privacy_pipeline_identity_tracks_face_bytes_and_settings(tmp_path):
    from edge_hub.privacy import privacy_pipeline_identity

    model = tmp_path / 'person.onnx'
    face = tmp_path / 'haarcascade-frontalface-default.xml'
    face.write_bytes(b'fixture-face-one')
    before = privacy_pipeline_identity(model)
    assert len(before['privacy_source_sha256']) == 64
    assert before['input_size'] == 416
    assert before['confidence_threshold'] == .15
    assert before != privacy_pipeline_identity(model, input_size=640)
    assert before != privacy_pipeline_identity(model, threshold=.2)
    assert before != privacy_pipeline_identity(model, retain_all=True)
    face.write_bytes(b'fixture-face-two')
    assert before != privacy_pipeline_identity(model)
    assert 'fixture-face' not in str(before)


class FakeInput:
    name = "images"


class FakePersonSession:
    def get_inputs(self):
        return [FakeInput()]

    def run(self, _outputs, inputs):
        assert inputs["images"].shape == (1, 3, 416, 416)
        rows = np.zeros((1, 3549, 85), dtype=np.float32)
        rows[0, 0, 4] = 0.95
        rows[0, 0, 5] = 0.95
        return [rows]


class FakeFaceCascade:
    def detectMultiScale(self, _gray, _scale, _neighbors):
        return []


def test_person_detector_decodes_yolox_and_returns_privacy_box() -> None:
    detector = PersonPrivacyDetector(
        Path("unused.onnx"), session=FakePersonSession(), face_cascade=FakeFaceCascade()
    )

    boxes = detector.detect(np.zeros((416, 416, 3), dtype=np.uint8))

    assert boxes
    assert all(value >= 0 for value in boxes[0])


def test_validation_union_keeps_overlapping_people_without_changing_default():
    class OverlapSession(FakePersonSession):
        def run(self, outputs, inputs):
            rows = np.zeros((1, 3549, 85), dtype=np.float32)
            rows[0, 0, :4] = [12.5, 12.5, np.log(10), np.log(10)]
            rows[0, 1, :4] = [12.75, 12.5, np.log(10), np.log(10)]
            rows[0, :2, 4:6] = .9
            return [rows]
    image = np.zeros((416, 416, 3), dtype=np.uint8)
    normal = PersonPrivacyDetector(Path('unused'), session=OverlapSession(),
                                   face_cascade=FakeFaceCascade())
    union = PersonPrivacyDetector(Path('unused'), session=OverlapSession(),
                                  face_cascade=FakeFaceCascade(), retain_all=True)
    assert len(normal.detect(image)) == 1
    assert len(union.detect(image)) == 2


@pytest.mark.parametrize("defect", ["nan", "infinity", "shape", "probability", "overflow"])
def test_person_detector_rejects_invalid_output_instead_of_no_people(defect) -> None:
    class InvalidSession(FakePersonSession):
        def run(self, outputs, inputs):
            rows = super().run(outputs, inputs)[0]
            if defect == "shape":
                return [rows[:, :-1]]
            column, value = {
                "nan": (5, float("nan")),
                "infinity": (4, float("inf")),
                "probability": (5, -0.1),
                "overflow": (2, 1000.0),
            }[defect]
            rows[0, 0, column] = value
            return [rows]

    detector = PersonPrivacyDetector(
        Path("unused.onnx"), session=InvalidSession(), face_cascade=FakeFaceCascade()
    )
    with pytest.raises(ValueError, match="privacy model output"):
        detector.detect(np.zeros((416, 416, 3), dtype=np.uint8))


def test_person_detector_does_not_mutate_session_output() -> None:
    class CachedSession(FakePersonSession):
        def run(self, outputs, inputs):
            if not hasattr(self, "rows"):
                self.rows = super().run(outputs, inputs)[0]
                self.rows.setflags(write=False)
            return [self.rows]

    session = CachedSession()
    detector = PersonPrivacyDetector(
        Path("unused.onnx"), session=session, face_cascade=FakeFaceCascade()
    )
    image = np.zeros((416, 416, 3), dtype=np.uint8)
    assert detector.detect(image) == detector.detect(image)


@pytest.mark.parametrize('threshold', [float('nan'), float('inf'), -0.1, 0, 1.1,
                                       True, '0.15', None])
def test_invalid_privacy_threshold_is_rejected_before_inference(threshold):
    class NoInference(FakePersonSession):
        def run(self, outputs, inputs):
            pytest.fail('invalid configuration entered the model')
    detector = PersonPrivacyDetector(Path('unused'), session=NoInference(),
                                     face_cascade=FakeFaceCascade())
    with pytest.raises(ValueError, match='privacy confidence threshold'):
        detector.detect(np.zeros((416, 416, 3), dtype=np.uint8), threshold=threshold)


@pytest.mark.parametrize('image', [None, np.zeros((0, 10, 3), dtype=np.uint8),
                                    np.zeros((10, 0, 3), dtype=np.uint8),
                                    np.zeros((10, 10), dtype=np.uint8),
                                    np.zeros((10, 10, 4), dtype=np.uint8),
                                    np.zeros((10, 10, 3), dtype=np.float32)])
def test_invalid_privacy_image_is_rejected_with_explicit_contract(image):
    detector = PersonPrivacyDetector(Path('unused'), session=FakePersonSession(),
                                     face_cascade=FakeFaceCascade())
    with pytest.raises(ValueError, match='privacy image'):
        detector.detect(image)


@pytest.mark.parametrize("box", [(0, 0, 0, 5), (0, 0, -2, 5), (30, 0, 5, 5),
                                (0, 0, 5), (0, 0, 1.5, 5), (False, 0, 5, 5)])
def test_invalid_privacy_box_cannot_be_silently_skipped(box) -> None:
    with pytest.raises(ValueError, match="privacy box"):
        blur_boxes(np.zeros((20, 20, 3), dtype=np.uint8), [box])


def test_partly_outside_privacy_box_is_clipped_and_masked() -> None:
    image = np.random.default_rng(0).integers(0, 256, (20, 20, 3), dtype=np.uint8)
    masked = blur_boxes(image, [(-3, -2, 10, 10)])
    assert not np.array_equal(masked[:8, :7], image[:8, :7])
    assert np.array_equal(masked[8:], image[8:])
