import json

import numpy as np

from tools.prepare_person_validation import (
    duplicate_audit,
    full_annotations,
    image_fingerprint,
    person_labels,
)


def test_labels_follow_official_person_descendants_not_body_parts(tmp_path):
    path = tmp_path / 'hierarchy.json'
    path.write_text(json.dumps({'LabelName': 'root', 'Subcategory': [
        {'LabelName': 'person', 'Subcategory': [{'LabelName': 'child'}]},
        {'LabelName': 'body-part'},
    ]}))
    assert person_labels(path, 'person') == {'person', 'child'}


def test_hashes_distinguish_exact_and_near_duplicates(tmp_path):
    import cv2

    first = tmp_path / 'first.png'
    second = tmp_path / 'second.png'
    image = np.tile(np.arange(32, dtype=np.uint8), (32, 1))
    cv2.imwrite(str(first), image)
    cv2.imwrite(str(second), image)
    left, right = image_fingerprint(first), image_fingerprint(second)
    assert left['sha256'] == right['sha256']
    report = duplicate_audit({'reg': left, 'val': right}, {'reg'}, {'val'})
    assert report['quarantined_validation_ids'] == ['val']
    assert len(report['exact_groups']) == 1
    report = duplicate_audit({'reg': {'sha256': 'a', 'dhash': '0000000000000000'},
                              'val': {'sha256': 'b', 'dhash': '0000000000000001'}}, {'reg'}, {'val'})
    assert report['near_pairs'][0]['distance'] == 1
    assert report['quarantined_validation_ids'] == ['val']
    assert report['source_group_independence_verified'] is False


def test_full_truth_keeps_small_occluded_truncated_and_group_boxes(tmp_path):
    path = tmp_path / 'boxes.csv'
    path.write_text('ImageID,LabelName,XMin,YMin,XMax,YMax,IsGroupOf,IsOccluded,IsTruncated\n'
                    'image,person,0,0,0.01,0.01,1,1,1\n'
                    'image,child,0,0,0.01,0.01,0,0,0\n'
                    'image,animal,0,0,1,1,0,0,0\n')
    boxes = full_annotations(path, {'person', 'child'}, {'image'})['image']
    assert len(boxes) == 1
    assert set(boxes[0]['labels']) == {'person', 'child'}
    assert boxes[0]['group'] and boxes[0]['occluded'] and boxes[0]['truncated']
