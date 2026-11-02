from collections import Counter

from tools.evaluate_litter_classifier import balanced_acceptance


def _crop_fixture(tmp_path, monkeypatch, labels, predictions, split='validation', **flags):
    import json
    from types import SimpleNamespace

    import cv2
    import numpy as np

    import tools.evaluate_litter_classifier as module

    items = []
    for index, label in enumerate(labels):
        name = f'{index}.jpg'
        cv2.imwrite(str(tmp_path / name), np.zeros((8, 8, 3), dtype=np.uint8))
        items.append({'path': name, 'label': label, 'split': split})
    (tmp_path / 'manifest.json').write_text(json.dumps({'items': items, **flags}))
    model = tmp_path / 'fake.onnx'
    model.write_bytes(b'fixture only, no inference')
    queue = iter(predictions)
    monkeypatch.setattr(module, 'OnnxCropClassifier', lambda _: SimpleNamespace(classify=lambda image: (next(queue), .9)))
    return module, model


def test_validation_perfect_crop_scores_cannot_pass_model_acceptance(tmp_path, monkeypatch):
    from edge_hub.vision import LITTER_CLASSES

    module, model = _crop_fixture(tmp_path, monkeypatch, LITTER_CLASSES, LITTER_CLASSES)
    result = module.evaluate(tmp_path, model, split='validation', min_samples_per_class=1)
    assert result['balanced_acceptance']['diagnostic_criteria_passed']
    assert not result['balanced_acceptance']['passed']
    assert result['evaluation_role'] == 'validation'
    assert result['formal_evaluation_eligible'] is False
    assert len(result['cohort_sha256']) == 64
    from edge_hub.vision import litter_pipeline_identity
    assert result['pipeline_identity'] == litter_pipeline_identity()


def test_crop_evaluation_rejects_pipeline_change_mid_run(tmp_path, monkeypatch):
    import pytest

    from edge_hub.vision import LITTER_CLASSES

    module, model = _crop_fixture(tmp_path, monkeypatch, LITTER_CLASSES, LITTER_CLASSES)
    calls = []
    def identity():
        calls.append(1)
        return {'fixture_pipeline_version': len(calls)}
    monkeypatch.setattr(module, 'litter_pipeline_identity', identity)
    with pytest.raises(ValueError, match='identity changed'):
        module.evaluate(tmp_path, model, split='validation', min_samples_per_class=1)


def test_background_false_accept_and_litter_rejection_count_without_unknown_class_error(tmp_path, monkeypatch):
    module, model = _crop_fixture(tmp_path, monkeypatch,
        ['plastic_bottle', 'background_unknown'], ['background_unknown', 'paper_cup'], split='test')
    result = module.evaluate(tmp_path, model)
    assert result['samples'] == 2
    assert result['metrics']['classes']['plastic_bottle']['fn'] == 1
    assert result['metrics']['classes']['paper_cup']['fp'] == 1


def test_provisional_test_does_not_gain_acceptance_from_perfect_scores(tmp_path, monkeypatch):
    from edge_hub.vision import LITTER_CLASSES

    module, model = _crop_fixture(tmp_path, monkeypatch, LITTER_CLASSES, LITTER_CLASSES,
                                  split='test', training_approved=False)
    result = module.evaluate(tmp_path, model, min_samples_per_class=1)
    assert result['balanced_acceptance']['diagnostic_criteria_passed']
    assert not result['balanced_acceptance']['passed']


def test_balanced_acceptance_rejects_an_underrepresented_class():
    metrics = {
        "classes": {
            label: {"precision": 0.9, "recall": 0.9}
            for label in ("plastic_bottle", "aluminium_can", "paper_cup", "paper_ball_package")
        }
    }
    counts = Counter(
        {
            "plastic_bottle": 100,
            "aluminium_can": 100,
            "paper_cup": 1,
            "paper_ball_package": 100,
        }
    )

    result = balanced_acceptance(metrics, counts, min_samples_per_class=20)

    assert result["macro_precision"] == 0.9
    assert result["macro_recall"] == 0.9
    assert result["coverage_passed"] is False
    assert result["passed"] is False


def test_balanced_acceptance_requires_each_class_to_reach_macro_target():
    metrics = {
        "classes": {
            "plastic_bottle": {"precision": 0.9, "recall": 0.9},
            "aluminium_can": {"precision": 0.8, "recall": 0.8},
            "paper_cup": {"precision": 0.8, "recall": 0.8},
            "paper_ball_package": {"precision": 0.7, "recall": 0.7},
        }
    }
    counts = Counter({label: 20 for label in metrics["classes"]})

    result = balanced_acceptance(metrics, counts, min_samples_per_class=20)

    assert result["macro_precision"] == 0.8
    assert result["macro_recall"] == 0.8
    assert result["per_class_passed"] is False
    assert result["passed"] is False
