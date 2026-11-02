import hashlib
import io
import json

import pytest

from edge_hub.events import EventStore
from edge_hub.vision import LITTER_CLASSES
from edge_hub.vision_runtime import VisionRuntime, _read_model_report


@pytest.fixture(params=['litter', 'person'])
def gate(tmp_path, monkeypatch, request):
    from edge_hub import vision_runtime as module

    monkeypatch.setattr(module, 'litter_pipeline_identity', lambda: {'fixture': 'identity'})
    monkeypatch.setattr(module, 'privacy_pipeline_identity', lambda path: {'fixture': 'identity'})
    monkeypatch.setattr(module.cv2, 'VideoCapture', lambda *a: pytest.fail('must not open camera'))
    monkeypatch.setenv('ZHIWEI_VISION_MODEL', str(tmp_path / 'models/litter.onnx'))
    monkeypatch.setenv('ZHIWEI_PERSON_MODEL', str(tmp_path / 'models/person.onnx'))
    store = EventStore()
    runtime = VisionRuntime(tmp_path, store, enabled=False)
    model = runtime.litter_model if request.param == 'litter' else runtime.person_model
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b'unit-fixture-not-an-inference-model')
    report = {'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
              'pipeline_identity': {'fixture': 'identity'}, 'evaluation_role': 'public-regression'}
    if request.param == 'litter':
        report.update(formal_evaluation_eligible=True, evaluation_scope='scene-events-with-background',
                      metrics={'classes': {label: {'precision': .9, 'recall': .9} for label in LITTER_CLASSES}},
                      balanced_acceptance={'passed': True, 'sample_counts': dict.fromkeys(LITTER_CLASSES, 20)})
        path, accepted = runtime.model_report, runtime._model_accepted
    else:
        report.update(masking_protocol='all-human-coverage-95-v3', mask_coverage_required=.95,
                      production_gate_eligible=True, ground_truth_scope='all_annotated_human_boxes',
                      annotation_audit={'human_label_coverage_verified': True, 'unscored_unique_human_boxes': 0},
                      inference_layout='full-frame', inference_calls_per_image=1,
                      evaluated=100, pass_rate=.95, passed=True)
        path = model.parent / 'person-privacy.report.json'
        accepted = runtime._privacy_accepted
    path.write_text(json.dumps(report), encoding='utf-8')
    assert accepted() is True
    try:
        yield path, accepted, report, runtime
    finally:
        store.close()


@pytest.mark.parametrize('change', ['duplicate', 'escaped_duplicate', 'nested_duplicate',
                                   'nan', 'infinity', 'overflow', 'deep', 'oversized'])
def test_model_gates_reject_invalid_json_without_changing_evidence_or_opening_camera(gate, change):
    path, accepted, report, runtime = gate
    raw = json.dumps(report)
    if change == 'duplicate':
        raw = '{"evaluation_role":"validation",' + raw[1:]
    elif change == 'escaped_duplicate':
        raw = '{"evaluation_rol\\u0065":"validation",' + raw[1:]
    else:
        metadata = {'nested_duplicate': '{"value":false,"value":true}',
                    'nan': 'NaN', 'infinity': 'Infinity', 'overflow': '1e999',
                    'deep': '[' * 2000 + '0' + ']' * 2000,
                    'oversized': '"' + 'x' * 2_000_000 + '"'}[change]
        raw = raw[:-1] + ',"metadata":' + metadata + '}'
    path.write_text(raw, encoding='utf-8')
    before = path.read_bytes()
    assert accepted() is False
    assert runtime.status()['enabled'] is False
    assert path.read_bytes() == before
    assert runtime._thread is None


def test_standard_bom_unicode_finite_report_keeps_existing_gate_behavior(gate):
    path, accepted, report, runtime = gate
    report['metadata'] = {'中文': [None, True, .25, 1e100], 'text': '[]"\\' * 1000}
    path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8-sig')
    assert accepted() is True
    assert runtime._thread is None


@pytest.mark.parametrize('value', [10**1000, -(10**1000)])
def test_huge_integer_scores_fail_closed_without_float_conversion_overflow(gate, value):
    path, accepted, report, runtime = gate
    if 'metrics' in report:
        report['metrics']['classes'][LITTER_CLASSES[0]]['precision'] = value
    else:
        report['pass_rate'] = value
    path.write_text(json.dumps(report), encoding='utf-8')
    assert accepted() is False
    assert runtime._thread is None


@pytest.mark.parametrize(('levels', 'expected'), [(62, True), (63, False)])
def test_explicit_report_depth_boundary_is_independent_of_python_recursion_limit(gate, levels, expected):
    path, accepted, report, runtime = gate
    nested = '[' * levels + '0' + ']' * levels
    raw = json.dumps(report)[:-1] + ',"metadata":{"nested":' + nested + '}}'
    path.write_text(raw, encoding='utf-8')
    assert accepted() is expected
    assert runtime._thread is None


def test_reader_limits_actual_read_without_trusting_stat():
    calls = []
    class Source(io.BytesIO):
        def read(self, size=-1):
            calls.append(size)
            return super().read(size)
    class Path:
        def open(self, mode):
            assert mode == 'rb'
            return Source(b' ' * 2_000_001)
    with pytest.raises(ValueError, match='size limit'):
        _read_model_report(Path())
    assert calls == [2_000_001]
