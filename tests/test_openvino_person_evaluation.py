import hashlib
import json

import cv2
import numpy as np
import pytest

from tools.evaluate_full_person_privacy import evaluate
from tools.evaluate_openvino_person import decode_ssd


def tensor():
    return np.zeros((1, 1, 200, 7), dtype=np.float32)


def test_ssd_scales_normalized_corners_and_clips_without_mutation():
    raw = tensor()
    raw[0, 0, 0] = [0, 1, .9, -.1, .25, .5, 1.2]
    saved = raw.copy()
    assert decode_ssd(raw, 200, 100, .15) == [(0, 25, 100, 75)]
    np.testing.assert_array_equal(saved, raw)


def test_ssd_terminator_and_below_threshold_are_not_people():
    raw = tensor()
    raw[0, 0, 0] = [0, 1, .1, 0, 0, 1, 1]
    raw[0, 0, 1, 0] = -1
    raw[0, 0, 2] = [0, 1, .9, 0, 0, 1, 1]
    assert decode_ssd(raw, 100, 100, .15) == []


@pytest.mark.parametrize('field,value', [(0, 2), (1, 2), (2, 2), (3, float('nan')), (5, -1)])
def test_invalid_ssd_output_fails(field, value):
    raw = tensor()
    raw[0, 0, 0] = [0, 1, .9, 0, 0, 1, 1]
    raw[0, 0, 0, field] = value
    with pytest.raises(ValueError):
        decode_ssd(raw, 100, 100, .15)


def test_wrong_ssd_shape_and_boolean_threshold_fail():
    with pytest.raises(ValueError):
        decode_ssd(np.zeros((200, 7)), 100, 100, .15)
    with pytest.raises(ValueError):
        decode_ssd(tensor(), 100, 100, True)


def test_0202_label_zero_is_person_not_background_and_padding_is_ignored():
    raw = tensor()
    raw[0, 0, 0] = [0, 0, .9, 0, 0, 1, 1]
    assert decode_ssd(raw, 100, 50, .15, person_label=0) == [(0, 0, 100, 50)]
    assert decode_ssd(raw, 100, 50, .15) == []
    raw[0, 0, 0, 1] = 1
    with pytest.raises(ValueError, match='header'):
        decode_ssd(raw, 100, 50, .15, person_label=0)


@pytest.mark.parametrize('label', [True, 2, -1, .0])
def test_unreviewed_person_label_rejected(label):
    with pytest.raises(ValueError, match='person label'):
        decode_ssd(tensor(), 100, 100, .15, person_label=label)


def test_research_adapter_cannot_request_regression_or_omit_identity(tmp_path):
    for role in ('validation', 'public-regression'):
        with pytest.raises(ValueError, match='validation only'):
            evaluate(tmp_path, tmp_path, tmp_path, tmp_path, role=role, research_detector=object())
    with pytest.raises(ValueError, match='validation only'):
        evaluate(tmp_path, tmp_path, tmp_path, tmp_path, role='public-regression',
                 research_detector=object(), research_identity=dict)


def test_perfect_research_fixture_still_cannot_pass_gate_and_detects_identity_drift(tmp_path):
    image_path = tmp_path / 'image.jpg'
    cv2.imwrite(str(image_path), np.zeros((10, 10, 3), dtype=np.uint8))
    raw = image_path.read_bytes()
    ids = [f'{index:016x}' for index in range(100)]
    for image_id in ids:
        (tmp_path / f'{image_id}.jpg').write_bytes(raw)
    prepared_path, provenance_path = tmp_path / 'prep.json', tmp_path / 'provenance.json'
    prepared_path.write_text(json.dumps({
        'regression_ids': [], 'all_hierarchy_person_annotations_included': True,
        'annotations': {i: [{'box_xyxy_normalized': [0, 0, 1, 1], 'group': False}]
                        for i in ids},
        'fingerprints': {i: {'sha256': hashlib.sha256(raw).hexdigest()} for i in ids},
    }))
    provenance_path.write_text(json.dumps({
        'preparation_sha256': hashlib.sha256(prepared_path.read_bytes()).hexdigest(),
        'validation_eligible_ids': ids,
    }))
    class Detector:
        def detect(self, *args, **kwargs):
            return [(0, 0, 10, 10)]
    report = evaluate(image_path, prepared_path, provenance_path, tmp_path,
                      research_detector=Detector(), research_identity=lambda: {'fake': True})
    assert report['passed_images'] == 100
    assert report['pass_rate'] == 1
    assert report['passed'] is False
    assert report['production_gate_eligible'] is False
    identities = iter([{'fixture': 1}, {'fixture': 2}])
    with pytest.raises(ValueError, match='pipeline changed'):
        evaluate(image_path, prepared_path, provenance_path, tmp_path,
                 research_detector=Detector(), research_identity=lambda: next(identities))
