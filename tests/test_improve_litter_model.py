from types import SimpleNamespace

import numpy as np
import pytest

from edge_hub.vision import LITTER_CLASSES, LitterFrameProcessor, OnnxCropClassifier
from tools.improve_litter_model import (
    audit_splits,
    class_report,
    intersects,
    negative_boxes,
    prepare,
)


def test_negative_sampling_avoids_all_annotated_boxes_and_is_repeatable():
    occupied = [(30, 30, 180, 100)]
    boxes = negative_boxes(320, 240, occupied, 7)
    assert boxes and boxes == negative_boxes(320, 240, occupied, 7)
    assert not any(intersects(box, region) for box in boxes for region in occupied)


def test_source_leakage_rejected_even_when_crop_paths_differ():
    with pytest.raises(ValueError, match='crosses splits'):
        audit_splits([{'path': 'a', 'source_identity': 'same-photo', 'split': 'train'},
                      {'path': 'b', 'source_identity': 'same-photo', 'split': 'test'}])


def test_background_false_accepts_count_against_target_precision():
    report = class_report(['plastic_bottle', 'background_unknown'], ['plastic_bottle'] * 2)
    assert report['plastic_bottle']['precision'] == .5
    assert report['background_unknown']['recall'] == 0


def test_unknown_class_never_becomes_a_litter_detection():
    class Session:
        def get_inputs(self):
            return [SimpleNamespace(name='image', shape=[1, 3, 160, 160])]

        def get_modelmeta(self):
            import json
            return SimpleNamespace(custom_metadata_map={
                'zhiwei_classes': json.dumps([*LITTER_CLASSES, 'background_unknown'])})

        def run(self, *_):
            return [np.array([[.01, .01, .01, .01, .96]], np.float32)]

    classifier = OnnxCropClassifier(None, session=Session())
    frame = np.zeros((80, 80, 3), np.uint8)
    assert classifier.classify(frame)[0] == 'background_unknown'
    candidates = SimpleNamespace(candidates=lambda _: [(0, 0, 40, 40)])
    processor = LitterFrameProcessor(classifier, candidates)
    assert processor.classify_candidates(frame) == []


def test_extension_preserves_existing_source_split_and_marks_weak_negatives(tmp_path):
    import json

    import cv2

    base, taco, output = (tmp_path / name for name in ('base', 'taco', 'output'))
    base.mkdir()
    (taco / 'batch_1').mkdir(parents=True)
    (base / 'manifest.json').write_text(json.dumps({'items': [
        {'path': 'original.jpg', 'label': 'plastic_bottle', 'source_group': 'zhiwei',
         'source_image': 'batch_1/one.jpg', 'split': 'train'}]}))
    cv2.imwrite(str(taco / 'batch_1/one.jpg'), np.full((240, 320, 3), 230, np.uint8))
    (taco / 'annotations.json').write_text(json.dumps({
        'images': [{'id': 1, 'file_name': 'batch_1/one.jpg', 'width': 640, 'height': 480}],
        'categories': [{'id': 1, 'name': 'Plastic film'}],
        'annotations': [{'id': 1, 'image_id': 1, 'category_id': 1, 'bbox': [200, 100, 80, 80]}]}))
    result = prepare(base, taco, output, max_images=1)
    assert {item['split'] for item in result['items']} == {'train'}
    added = result['items'][1:]
    assert any(x['label'] == 'paper_ball_package' for x in added)
    assert any(x['weak_negative'] for x in added)
    assert result['independent_source_images'] == 1
