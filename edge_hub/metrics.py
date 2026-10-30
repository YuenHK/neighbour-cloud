from __future__ import annotations

from dataclasses import dataclass

from edge_hub.vision import LITTER_CLASSES


@dataclass(frozen=True)
class LabeledBox:
    image: str
    label: str
    box: tuple[float, float, float, float]
    confidence: float = 1.0


def intersection_over_union(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    overlap_width = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    overlap_height = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    intersection = overlap_width * overlap_height
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def detection_metrics(
    ground_truth: list[LabeledBox],
    predictions: list[LabeledBox],
    *,
    iou_threshold: float = 0.5,
    confidence_threshold: float = 0.5,
) -> dict[str, object]:
    if not 0.0 < iou_threshold <= 1.0:
        raise ValueError("IoU threshold must be between 0 and 1")
    all_items = [*ground_truth, *predictions]
    unknown_labels = {item.label for item in all_items} - set(LITTER_CLASSES)
    if unknown_labels:
        raise ValueError(f"unknown litter classes: {sorted(unknown_labels)}")
    if any(item.box[2] <= 0 or item.box[3] <= 0 for item in all_items):
        raise ValueError("box width and height must be positive")

    class_results: dict[str, dict[str, float | int]] = {}
    totals = {"tp": 0, "fp": 0, "fn": 0}
    for label in LITTER_CLASSES:
        truths = [item for item in ground_truth if item.label == label]
        predicted = sorted(
            (
                item
                for item in predictions
                if item.label == label and item.confidence >= confidence_threshold
            ),
            key=lambda item: item.confidence,
            reverse=True,
        )
        matched_truths: set[int] = set()
        true_positives = 0
        for prediction in predicted:
            candidates = [
                (index, intersection_over_union(prediction.box, truth.box))
                for index, truth in enumerate(truths)
                if index not in matched_truths and truth.image == prediction.image
            ]
            best = max(candidates, key=lambda item: item[1], default=None)
            if best is not None and best[1] >= iou_threshold:
                matched_truths.add(best[0])
                true_positives += 1

        false_positives = len(predicted) - true_positives
        false_negatives = len(truths) - true_positives
        precision_denominator = true_positives + false_positives
        recall_denominator = true_positives + false_negatives
        class_results[label] = {
            "tp": true_positives,
            "fp": false_positives,
            "fn": false_negatives,
            "precision": true_positives / precision_denominator if precision_denominator else 0.0,
            "recall": true_positives / recall_denominator if recall_denominator else 0.0,
        }
        totals["tp"] += true_positives
        totals["fp"] += false_positives
        totals["fn"] += false_negatives

    precision = totals["tp"] / (totals["tp"] + totals["fp"]) if totals["tp"] + totals["fp"] else 0.0
    recall = totals["tp"] / (totals["tp"] + totals["fn"]) if totals["tp"] + totals["fn"] else 0.0
    return {
        **totals,
        "precision": precision,
        "recall": recall,
        "target": 0.8,
        "passed": precision >= 0.8 and recall >= 0.8,
        "classes": class_results,
    }
