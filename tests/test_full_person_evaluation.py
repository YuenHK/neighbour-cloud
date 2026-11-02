import hashlib
import json

import pytest

from tools.evaluate_full_person_privacy import evaluate, score_frame


@pytest.mark.parametrize('tiles,retain_all', [(False, False), (True, True)])
def test_evaluator_records_pipeline_identity_without_production_promotion(tmp_path, monkeypatch,
                                                                         tiles, retain_all):
    import cv2
    import numpy as np

    from edge_hub.privacy import privacy_pipeline_identity
    from tools import evaluate_full_person_privacy as tool

    model, prepared, provenance = [tmp_path / name for name in ('model', 'prep.json', 'source.json')]
    model.write_bytes(b'fixture weights never loaded')
    image_id = 'a' * 16
    image = tmp_path / f'{image_id}.jpg'
    cv2.imwrite(str(image), np.zeros((20, 20, 3), dtype=np.uint8))
    prepared.write_text(json.dumps({
        'regression_ids': [], 'all_hierarchy_person_annotations_included': True,
        'annotations': {image_id: [{'box_xyxy_normalized': [0, 0, 1, 1], 'group': False}]},
        'fingerprints': {image_id: {'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}},
    }), encoding='utf-8')
    provenance.write_text(json.dumps({'preparation_sha256': hashlib.sha256(prepared.read_bytes()).hexdigest(),
                                     'validation_eligible_ids': [image_id]}), encoding='utf-8')
    calls = []
    class Detector:
        def __init__(self, *args, **kwargs):
            assert kwargs['retain_all'] == retain_all
        def detect(self, *args, **kwargs):
            calls.append(args[0].shape)
            return [(0, 0, 20, 20)]
    monkeypatch.setattr(tool, 'PersonPrivacyDetector', Detector)
    result = evaluate(model, prepared, provenance, tmp_path, tiles=tiles, retain_all=retain_all)
    assert result['pipeline_identity'] == privacy_pipeline_identity(model, retain_all=retain_all)
    assert result['inference_calls_per_image'] == (5 if tiles else 1)
    assert len(calls) == (5 if tiles else 1)
    assert result['inference_layout'] == ('full-plus-four-60pct-corners' if tiles else 'full-frame')
    assert result['production_gate_eligible'] is False
    assert result['passed'] is False  # one synthetic validation image is not acceptance
    class ChangingDetector(Detector):
        def __init__(self, *args, **kwargs):
            (tmp_path / 'haarcascade-frontalface-default.xml').write_bytes(b'changed-mid-evaluation')
    monkeypatch.setattr(tool, 'PersonPrivacyDetector', ChangingDetector)
    with pytest.raises(ValueError, match='pipeline changed'):
        evaluate(model, prepared, provenance, tmp_path)


def test_overlapping_tiles_preserve_full_frame_and_translate_boxes():
    import numpy as np

    from tools.evaluate_full_person_privacy import detect_with_tiles

    class Detector:
        def __init__(self):
            self.shapes = []

        def detect(self, image, threshold):
            assert threshold == .15
            self.shapes.append(image.shape[:2])
            return [(0, 0, 5, 5)]

    detector = Detector()
    boxes = detect_with_tiles(detector, np.zeros((100, 200, 3), dtype=np.uint8), .15)
    assert detector.shapes == [(100, 200)] + [(60, 120)] * 4
    assert boxes == [(0, 0, 5, 5), (0, 0, 5, 5), (80, 0, 5, 5),
                     (0, 40, 5, 5), (80, 40, 5, 5)]


def test_tiled_diagnostic_cannot_use_public_regression(tmp_path):
    with pytest.raises(ValueError, match='validation only'):
        evaluate(tmp_path / 'model', tmp_path / 'prep', tmp_path / 'provenance',
                 tmp_path, role='public-regression', tiles=True)


@pytest.mark.parametrize('tiles', [False, True])
def test_unsuppressed_union_cannot_use_public_regression(tmp_path, tiles):
    with pytest.raises(ValueError, match='validation only'):
        evaluate(tmp_path / 'model', tmp_path / 'prep', tmp_path / 'provenance',
                 tmp_path, role='public-regression', retain_all=True, tiles=tiles)


def test_tile_failure_is_not_silently_dropped():
    import numpy as np

    from tools.evaluate_full_person_privacy import detect_with_tiles

    class Detector:
        def detect(self, image, threshold):
            if image.shape[0] < 100:
                raise ValueError('tile failure')
            return []

    with pytest.raises(ValueError, match='tile failure'):
        detect_with_tiles(Detector(), np.zeros((100, 200, 3), dtype=np.uint8), .15)


def test_groups_require_entire_region_not_a_mostly_covered_crowd():
    truth = {'box_xyxy_normalized': [0, 0, 1, 1], 'group': False}
    assert score_frame([truth], [(0, 0, 96, 100)], 100, 100)['passed']
    truth['group'] = True
    assert not score_frame([truth], [(0, 0, 96, 100)], 100, 100)['passed']
    assert score_frame([truth], [(0, 0, 100, 100)], 100, 100)['passed']


def test_small_or_occluded_people_cannot_be_filtered_out_of_score():
    truths = [{'box_xyxy_normalized': [0, 0, .5, 1], 'group': False},
              {'box_xyxy_normalized': [.9, .9, 1, 1], 'group': False, 'occluded': True}]
    result = score_frame(truths, [(0, 0, 50, 100)], 100, 100)
    assert result['boxes_scored'] == 2
    assert result['minimum_coverage'] == 0
    assert not result['passed']


def test_stale_provenance_is_rejected_before_loading_any_model(tmp_path):
    prepared = tmp_path / 'prepared.json'
    provenance = tmp_path / 'provenance.json'
    prepared.write_text('{}')
    provenance.write_text(json.dumps({'preparation_sha256': 'different'}))
    with pytest.raises(ValueError, match='stale provenance'):
        evaluate(tmp_path / 'nonexistent-model', prepared, provenance, tmp_path)
