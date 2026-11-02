from tools.evaluate_person_privacy import box_is_masked


def test_candidate_report_keeps_scope_hash_and_explicit_input_size(tmp_path, monkeypatch):
    import numpy as np

    from tools import evaluate_person_privacy as evaluator

    class Detector:
        def __init__(self, path, input_size):
            assert path == model
            assert input_size == 640

        def detect(self, image, threshold):
            assert threshold == 0.15
            return [(0, 0, 20, 20)]

    model = tmp_path / "candidate.onnx"
    model.write_bytes(b"test model")
    monkeypatch.setattr(evaluator, "load_person_boxes", lambda *_: {"public": [(0, 0, 1, 1)]})
    monkeypatch.setattr(evaluator, "download_image", lambda *_: True)
    monkeypatch.setattr(evaluator.cv2, "imread", lambda *_: np.zeros((20, 20, 3), np.uint8))
    monkeypatch.setattr(evaluator, "PersonPrivacyDetector", Detector)
    result = evaluator.evaluate(model, model, model, tmp_path, 1, 0.15, 640)
    assert result["input_size"] == 640
    assert len(result["model_sha256"]) == 64
    assert result["detect_ms_p95"] >= 0
    assert "not fresh or onsite" in result["evaluation_scope"]
    assert result["passed_images"] == 1


def test_full_person_overlap_counts_as_masked() -> None:
    assert box_is_masked((0, 0, 100, 200), [(1, 1, 98, 198)]) is True


def test_face_only_does_not_count_as_full_person_masked() -> None:
    assert box_is_masked((0, 0, 100, 200), [(35, 10, 30, 30)]) is False


def test_union_counts_coverage_without_double_counting_overlap():
    assert box_is_masked((0, 0, 100, 200), [(0, 0, 100, 100), (0, 100, 100, 100)])
    assert not box_is_masked((0, 0, 100, 200), [(0, 0, 100, 100)] * 3)


def test_unrelated_box_does_not_count_as_masked() -> None:
    assert box_is_masked((0, 0, 100, 200), [(200, 200, 30, 30)]) is False
