import csv

from tools.audit_person_annotations import audit_annotations, select_validation
from tools.evaluate_person_privacy import coverage_ratio


def test_coverage_diagnostics_preserve_exact_union_rule():
    assert coverage_ratio((0, 0, 100, 100), [(0, 0, 100, 50)] * 2) == .5
    assert coverage_ratio((0, 0, 100, 100), [(0, 0, 100, 50), (0, 50, 100, 50)]) == 1
    assert coverage_ratio((0, 0, 0, 100), []) == 0


def test_audit_finds_ignored_small_occluded_and_human_label_boxes(tmp_path):
    classes = tmp_path / 'classes.csv'
    classes.write_text('/person,Person\n/man,Man\n/cat,Cat\n', encoding='utf-8')
    boxes = tmp_path / 'boxes.csv'
    fields = ['ImageID', 'LabelName', 'XMin', 'YMin', 'XMax', 'YMax',
              'IsGroupOf', 'IsOccluded', 'IsTruncated']
    with boxes.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for label, x, y, right, bottom, occluded in [
            ('/person', 0, 0, .5, .8, 0),
            ('/man', 0, 0, .5, .8, 0),  # exact same box is not an additional unique box
            ('/person', .8, .8, .9, .9, 1),
            ('/man', .6, .1, .8, .8, 0),
            ('/cat', 0, 0, 1, 1, 0),
        ]:
            writer.writerow(dict(zip(fields, ['image', label, x, y, right, bottom, 0, occluded, 0])))
    report = audit_annotations(classes, boxes, {'image': [(0, 0, .5, .8)]})
    assert report['images_with_unscored_unique_human_boxes'] == 1
    assert report['unscored_unique_human_boxes'] == 2
    assert report['human_label_names_found'] == ['Man', 'Person']
    assert report['complete_privacy_acceptance'] is False


def test_validation_ids_are_deterministic_and_disjoint():
    grouped = {'a': [], 'b': [], 'c': [], 'd': []}
    assert select_validation(grouped, {'a', 'c'}, 2) == ['b', 'd']
    assert select_validation(grouped, set(grouped), 2) == []
