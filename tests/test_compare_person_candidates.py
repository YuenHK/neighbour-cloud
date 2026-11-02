import copy
import hashlib
import json

import pytest

from tools.compare_person_candidates import compare


def diagnostic_fixture():
    prepared = json.dumps({'regression_ids': [], 'annotations': {
        'a': [{'box_xyxy_normalized': [0, 0, 1, 1], 'group': True,
               'occluded': False, 'truncated': False}],
        'b': [{'box_xyxy_normalized': [0, 0, .05, .05], 'group': False,
               'occluded': True, 'truncated': True}],
    }}).encode()
    candidate = report(1, 'fixture')
    candidate['preparation_sha256'] = hashlib.sha256(prepared).hexdigest()
    candidate['results'][0].update(boxes_scored=1, box_coverages=[1.], group_boxes=1)
    candidate['results'][1].update(boxes_scored=1, box_coverages=[.1], group_boxes=0)
    return candidate, prepared


def test_failure_analysis_retains_small_occluded_boxes_and_strict_group_rule():
    from tools.compare_person_candidates import analyze_failures

    candidate, prepared = diagnostic_fixture()
    result = analyze_failures(candidate, prepared)
    assert result['strata']['area_lt_1pct']['failed_boxes'] == 1
    assert result['strata']['occluded']['failed_boxes'] == 1
    assert result['strata']['truncated']['failed_boxes'] == 1
    assert result['failed_frames'][0]['image'] == 'b'
    assert result['failed_frames'][0]['failed_boxes'][0]['box_xyxy_normalized'] == [0, 0, .05, .05]
    candidate['results'][0].update(passed=False, box_coverages=[.96])
    candidate.update(passed_images=0, pass_rate=0.)
    result = analyze_failures(candidate, prepared)
    assert result['strata']['group']['failed_boxes'] == 1
    assert len(result['failed_frames']) == 2


def test_failure_analysis_rejects_stale_source_or_missing_box_scores():
    from tools.compare_person_candidates import analyze_failures

    candidate, prepared = diagnostic_fixture()
    with pytest.raises(ValueError):
        analyze_failures(candidate, prepared + b' ')
    candidate['results'][1]['box_coverages'] = []
    with pytest.raises(ValueError):
        analyze_failures(candidate, prepared)


def test_failure_analysis_keeps_unavailable_in_denominator():
    from tools.compare_person_candidates import analyze_failures

    candidate, prepared = diagnostic_fixture()
    candidate['results'].pop()
    candidate.update(evaluated=1, unavailable=['b'])
    result = analyze_failures(candidate, prepared)
    assert result['requested'] == 2
    assert result['unavailable'] == ['b']
    assert result['unscored_boxes'] == 1


def report(score, model):
    return {'evaluation_role': 'validation', 'masking_protocol': 'all-human-coverage-95-v3',
            'preparation_sha256': 'prep', 'provenance_sha256': 'source',
            'group_policy': 'full group', 'mask_coverage_required': .95, 'confidence_threshold': .15,
            'requested': 2, 'evaluated': 2, 'unavailable': [], 'pass_rate': score / 2,
            'passed_images': score, 'model_sha256': model, 'detect_ms_p95': 100,
            'annotation_audit': {'human_label_coverage_verified': True, 'unscored_unique_human_boxes': 0},
            'results': [{'image': 'a', 'passed': True, 'group_boxes': 0},
                        {'image': 'b', 'passed': score == 2, 'group_boxes': 1}]}


def test_comparison_is_analysis_only_and_records_improved_cases():
    result = compare([report(1, 'baseline'), report(2, 'candidate')])
    assert result['analysis_candidate_sha256'] == 'candidate'
    assert result['comparisons'][1]['improved_ids'] == ['b']
    assert result['ready_for_regression'] is False  # too few images
    assert result['production_model_modified'] is False


@pytest.mark.parametrize('field,value', [('evaluation_role', 'public-regression'),
                                        ('preparation_sha256', 'different'),
                                        ('group_policy', 'relaxed'),
                                        ('confidence_threshold', .01)])
def test_comparison_rejects_test_selection_or_incomparable_protocols(field, value):
    baseline = report(1, 'baseline')
    candidate = copy.deepcopy(baseline)
    candidate[field] = value
    with pytest.raises(ValueError):
        compare([baseline, candidate])


def test_missing_failed_image_cannot_improve_the_score():
    baseline = report(1, 'baseline')
    candidate = report(2, 'candidate')
    candidate['results'].pop()
    candidate['requested'] = candidate['evaluated'] = 1
    with pytest.raises(ValueError):
        compare([baseline, candidate])


def test_uncontrolled_latency_does_not_select_a_model_on_a_coverage_tie():
    baseline = report(1, 'baseline')
    faster = report(1, 'faster-under-different-load')
    faster['detect_ms_p95'] = 1
    assert compare([baseline, faster])['analysis_candidate_sha256'] == 'baseline'


def test_same_weights_with_different_inference_layouts_remain_distinct():
    baseline = report(1, 'same-weights')
    baseline.update(input_size=416, inference_layout='full-frame', inference_calls_per_image=1)
    tiled = report(2, 'same-weights')
    tiled.update(input_size=416, inference_layout='full-plus-four-60pct-corners',
                 inference_calls_per_image=5, masked_frame_fraction_mean=.46)
    result = compare([baseline, tiled])
    first, second = result['comparisons']
    assert first['candidate_id'] != second['candidate_id']
    assert result['analysis_candidate_id'] == second['candidate_id']
    assert second['inference_configuration']['inference_calls_per_image'] == 5
    assert second['masked_frame_fraction_mean'] == .46
    assert first['masked_frame_fraction_mean'] is None


def test_legacy_reports_do_not_invent_missing_layout_or_call_count():
    result = compare([report(1, 'old'), report(2, 'other')])
    config = result['comparisons'][0]['inference_configuration']
    assert config['inference_layout'] is None
    assert config['inference_calls_per_image'] is None
    assert config['pipeline_identity'] is None


def test_changed_recorded_pipeline_changes_candidate_identity_without_relabeling_history():
    baseline = report(1, 'same-weights')
    revised = copy.deepcopy(baseline)
    revised['pipeline_identity'] = {'privacy_source_sha256': 'new-recorded-source'}
    result = compare([baseline, revised])
    assert result['comparisons'][0]['candidate_id'] != result['comparisons'][1]['candidate_id']
    assert 'pipeline_identity' not in baseline
