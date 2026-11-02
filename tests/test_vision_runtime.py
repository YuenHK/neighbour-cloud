import hashlib
import json

import pytest

from edge_hub.events import EventStore
from edge_hub.privacy import privacy_pipeline_identity
from edge_hub.vision_runtime import VisionRuntime, configured_vision_enabled


def test_runtime_can_be_deliberately_disabled(tmp_path):
    runtime = VisionRuntime(tmp_path, EventStore(tmp_path / "events.json"), enabled=False)

    runtime.start()

    assert runtime.status()["enabled"] is False
    assert runtime.status()["status"] == "disabled"


def test_runtime_rejects_model_without_passing_report(tmp_path):
    model = tmp_path / "models" / "litter-classifier.onnx"
    model.parent.mkdir()
    model.write_bytes(b"not-used")
    runtime = VisionRuntime(tmp_path, EventStore(tmp_path / "events.json"), enabled=True)

    runtime.start()

    assert runtime.status()["status"] == "waiting_for_models"
    assert runtime.status()["litter_model_accepted"] is False


def test_runtime_accepts_only_passing_model_report(tmp_path, monkeypatch):
    model_root = tmp_path / "models"
    model_root.mkdir()
    litter_model = model_root / "litter-classifier.onnx"
    person_model = model_root / "person-yolox-tiny.onnx"
    litter_model.write_bytes(b"not-used")
    person_model.write_bytes(b"not-used")
    (model_root / 'person-privacy.report.json').write_text(json.dumps({
        'masking_protocol': 'all-human-coverage-95-v3', 'mask_coverage_required': 0.95,
        'evaluation_role': 'public-regression', 'production_gate_eligible': True,
        'ground_truth_scope': 'all_annotated_human_boxes',
        'annotation_audit': {'human_label_coverage_verified': True, 'unscored_unique_human_boxes': 0},
        'model_sha256': hashlib.sha256(person_model.read_bytes()).hexdigest(),
        'pipeline_identity': privacy_pipeline_identity(person_model),
        'inference_layout': 'full-frame', 'inference_calls_per_image': 1,
        'evaluated': 100, 'pass_rate': 0.95, 'passed': True,
    }), encoding='utf-8')
    litter_model.with_suffix(".report.json").write_text(
        json.dumps(passing_litter_report(litter_model)),
        encoding="utf-8",
    )
    runtime = VisionRuntime(tmp_path, EventStore(tmp_path / "events.json"), enabled=True)
    monkeypatch.setattr(runtime, "_run", lambda: None)

    runtime.start()
    runtime._thread.join(timeout=1)

    assert runtime.status()["litter_model_accepted"] is True
    assert runtime.status()["person_model_ready"] is True
    assert runtime.status()["person_privacy_accepted"] is True
    report_path = model_root / 'person-privacy.report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    for field, value in [('pipeline_identity', None), ('pipeline_identity', {}),
                         ('inference_layout', 'full-plus-four-60pct-corners'),
                         ('inference_calls_per_image', 5)]:
        changed = dict(report, **{field: value})
        report_path.write_text(json.dumps(changed), encoding='utf-8')
        assert runtime._privacy_accepted() is False
    for field, value in [('input_size', 640), ('confidence_threshold', .2),
                         ('privacy_source_sha256', 'changed-source'),
                         ('face_model_sha256', 'changed-face'), ('opencv_version', 'changed'),
                         ('person_box_policy', 'all-qualified')]:
        changed = dict(report, pipeline_identity={**report['pipeline_identity'], field: value})
        report_path.write_text(json.dumps(changed), encoding='utf-8')
        assert runtime._privacy_accepted() is False
    for invalid_rate in (True, float('inf'), 1.1, '0.99'):
        report['pass_rate'] = invalid_rate
        report_path.write_text(json.dumps(report), encoding='utf-8')
        assert runtime._privacy_accepted() is False
    report['pass_rate'] = .95
    report['evaluated'] = 100.5
    report_path.write_text(json.dumps(report), encoding='utf-8')
    assert runtime._privacy_accepted() is False
    report['evaluated'] = 100
    report['evaluation_role'] = 'validation'
    report_path.write_text(json.dumps(report), encoding='utf-8')
    assert runtime.status()["person_privacy_accepted"] is False
    report['evaluation_role'] = 'public-regression'
    report_path.write_text(json.dumps(report), encoding='utf-8')
    face_path = model_root / 'haarcascade-frontalface-default.xml'
    face_path.write_bytes(b'changed face file cannot inherit an older report')
    assert runtime._privacy_accepted() is False
    person_model.write_bytes(b'changed model cannot inherit an older report')
    assert runtime.status()["person_privacy_accepted"] is False


def test_overall_average_cannot_override_failing_class_metrics(tmp_path):
    model = tmp_path / 'models/litter-classifier.onnx'
    model.parent.mkdir()
    model.write_bytes(b'unit test')
    model.with_suffix('.report.json').write_text(json.dumps({
        'metrics': {'passed': True, 'classes': {
            label: {'precision': 0.9, 'recall': 0.7}
            for label in ('plastic_bottle', 'aluminium_can', 'paper_cup', 'paper_ball_package')
        }}, 'balanced_acceptance': {'passed': True},
    }), encoding='utf-8')
    runtime = VisionRuntime(tmp_path, EventStore())
    assert runtime.status()['litter_model_accepted'] is False


def test_old_face_only_privacy_report_is_not_accepted(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    (root / 'person-privacy.report.json').write_text(json.dumps({
        'evaluated': 100, 'pass_rate': 0.95, 'passed': True,
    }), encoding='utf-8')
    assert VisionRuntime(tmp_path, EventStore()).status()['person_privacy_accepted'] is False


def test_old_report_without_pipeline_binding_is_not_accepted(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    model = root / 'person-yolox-tiny.onnx'
    model.write_bytes(b'fixture-model')
    (root / 'person-privacy.report.json').write_text(json.dumps({
        'masking_protocol': 'all-human-coverage-95-v3', 'mask_coverage_required': .95,
        'evaluation_role': 'public-regression', 'production_gate_eligible': True,
        'ground_truth_scope': 'all_annotated_human_boxes',
        'annotation_audit': {'human_label_coverage_verified': True, 'unscored_unique_human_boxes': 0},
        'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
        'evaluated': 100, 'pass_rate': 1., 'passed': True,
    }), encoding='utf-8')
    assert VisionRuntime(tmp_path, EventStore())._privacy_accepted() is False


def test_eligible_person_only_report_cannot_pass_even_with_perfect_score(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    (root / 'person-privacy.report.json').write_text(json.dumps({
        'masking_protocol': 'person-coverage-95-v2', 'mask_coverage_required': .95,
        'evaluated': 100, 'pass_rate': 1., 'passed': True,
    }), encoding='utf-8')
    assert VisionRuntime(tmp_path, EventStore()).status()['person_privacy_accepted'] is False


def test_missing_or_unknown_vision_opt_in_never_starts_a_worker(tmp_path, monkeypatch):
    monkeypatch.delenv('ZHIWEI_VISION_ENABLED', raising=False)
    for value in (None, '', 'typo', 'false', '0'):
        if value is not None:
            monkeypatch.setenv('ZHIWEI_VISION_ENABLED', value)
        runtime = VisionRuntime(tmp_path, EventStore())
        runtime.start()
        assert runtime.status()['enabled'] is False
        assert runtime._thread is None


def passing_litter_report(model):
    from edge_hub.vision import litter_pipeline_identity

    labels = ('plastic_bottle', 'aluminium_can', 'paper_cup', 'paper_ball_package')
    return {'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
            'evaluation_role': 'public-regression', 'formal_evaluation_eligible': True,
            'evaluation_scope': 'scene-events-with-background', 'pipeline_identity': litter_pipeline_identity(),
            'metrics': {'classes': {label: {'precision': .9, 'recall': .9} for label in labels}},
            'balanced_acceptance': {'passed': True, 'sample_counts': dict.fromkeys(labels, 20)}}


@pytest.mark.parametrize('change', ['model', 'validation', 'crop', 'ineligible', 'coverage', 'infinite', 'list'])
def test_litter_gate_rejects_unbound_or_diagnostic_report(tmp_path, change):
    model = tmp_path / 'models/litter-classifier.onnx'
    model.parent.mkdir()
    model.write_bytes(b'first-model')
    report = passing_litter_report(model)
    runtime = VisionRuntime(tmp_path, EventStore(), enabled=False)
    path = model.with_suffix('.report.json')
    path.write_text(json.dumps(report), encoding='utf-8')
    assert runtime._model_accepted()
    if change == 'model':
        model.write_bytes(b'different-model')
    elif change == 'validation':
        report['evaluation_role'] = 'validation'
    elif change == 'crop':
        report['evaluation_scope'] = 'crop-classification'
    elif change == 'ineligible':
        report['formal_evaluation_eligible'] = False
    elif change == 'coverage':
        report['balanced_acceptance']['sample_counts']['paper_cup'] = 0
    elif change == 'infinite':
        report['metrics']['classes']['paper_cup']['precision'] = float('inf')
    else:
        report = []
    path.write_text(json.dumps(report), encoding='utf-8')
    assert runtime._model_accepted() is False


def test_vision_marker_is_explicit_and_overrides_environment(tmp_path, monkeypatch):
    marker = tmp_path / 'vision-enabled.txt'
    monkeypatch.setenv('ZHIWEI_VISION_ENABLED', 'true')
    assert configured_vision_enabled(marker)
    for text, expected in [('false', False), ('typo', False), ('', False), (' TRUE\n', True)]:
        marker.write_text(text, encoding='ascii')
        assert configured_vision_enabled(marker) is expected
    marker.write_bytes(b'\xff')
    assert configured_vision_enabled(marker) is False


def test_unreadable_vision_marker_is_not_an_opt_in(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise PermissionError('not readable')
    monkeypatch.setattr(type(tmp_path), 'read_text', unavailable)
    monkeypatch.setenv('ZHIWEI_VISION_ENABLED', 'true')
    assert configured_vision_enabled(tmp_path / 'vision-enabled.txt') is False
