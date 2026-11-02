import pytest

from edge_hub.metrics import LabeledBox, detection_metrics, intersection_over_union


def box(image: str, label: str, x: float, confidence: float = 1.0) -> LabeledBox:
    return LabeledBox(image, label, (x, 0, 10, 10), confidence)


def test_iou_for_identical_and_disjoint_boxes() -> None:
    assert intersection_over_union((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert intersection_over_union((0, 0, 10, 10), (20, 20, 10, 10)) == 0.0


def test_metrics_match_only_same_image_class_and_box() -> None:
    truth = [box("a.jpg", "plastic_bottle", 0), box("b.jpg", "plastic_bottle", 0)]
    predictions = [
        box("a.jpg", "plastic_bottle", 0, 0.9),
        box("b.jpg", "plastic_bottle", 20, 0.8),
        box("other.jpg", "plastic_bottle", 0, 0.7),
    ]

    result = detection_metrics(truth, predictions)

    assert result["tp"] == 1
    assert result["fp"] == 2
    assert result["fn"] == 1
    assert result["precision"] == 1 / 3
    assert result["recall"] == 1 / 2
    assert result["passed"] is False


def test_metrics_pass_at_80_percent_precision_and_recall() -> None:
    truth = [box(f"{index}.jpg", "paper_cup", 0) for index in range(5)]
    predictions = [box(f"{index}.jpg", "paper_cup", 0, 0.9) for index in range(4)]

    result = detection_metrics(truth, predictions)

    assert result["precision"] == 1.0
    assert result["recall"] == 0.8
    assert result["passed"] is True


def test_unknown_class_is_rejected_instead_of_silently_ignored() -> None:
    with pytest.raises(ValueError, match="unknown litter"):
        detection_metrics([box("a.jpg", "unknown", 0)], [])
