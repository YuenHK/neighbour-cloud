from pathlib import Path

import pytest

from tools.audit_litter_labels import audit, label_quality
from tools.augment_litter_dataset import add_open_images_cups, add_trashnet


def test_generic_material_or_coffee_cup_is_not_a_verified_project_class():
    assert label_quality({'source': 'TrashNet', 'label': 'plastic_bottle'})[0] == 'review'
    assert label_quality({'source': 'Open Images V7 Coffee cup', 'label': 'paper_cup'})[0] == 'review'
    assert label_quality({'source_class': 'Drink can', 'label': 'aluminium_can'})[0] == 'aligned'


def test_bower_bottle_is_specific_but_can_tin_cylinder_does_not_prove_aluminium():
    assert label_quality({'source_group': 'bower', 'material': 'Plastic - Hard',
                          'object': 'Bottle', 'label': 'plastic_bottle'})[0] == 'aligned'
    assert label_quality({'source_group': 'bower', 'material': 'Metal',
                          'object': 'Can/Tin/Cylinder', 'label': 'aluminium_can'})[0] == 'review'


def test_audit_preserves_splits_and_exposes_empty_strict_test_classes():
    items = [{'path': 'a.jpg', 'source_class': 'Drink can', 'label': 'aluminium_can', 'split': 'train'},
             {'path': 'b.jpg', 'source': 'TrashNet', 'label': 'aluminium_can', 'split': 'test'}]
    report, subset = audit({'items': items})
    assert report['review_count'] == 1
    assert subset['items'][0]['split'] == 'train'
    assert 'test/aluminium_can' in report['strict_missing_event_classes']
    assert subset['training_approved'] is False
    assert items[1]['source'] == 'TrashNet'  # input remains unchanged


def test_weak_import_requires_explicit_opt_in_before_reading_any_archive(tmp_path):
    with pytest.raises(ValueError, match='weak'):
        add_trashnet(tmp_path, Path('nonexistent.zip'))
    with pytest.raises(ValueError, match='weak'):
        add_open_images_cups(tmp_path, Path('nonexistent.csv'), tmp_path)


def test_provisional_manifest_cannot_start_training(tmp_path):
    from tools.train_litter_mobilenet import train

    (tmp_path / 'manifest.json').write_text('{"training_approved": false}')
    with pytest.raises(ValueError, match='not approved'):
        train(tmp_path, tmp_path / 'unused.onnx', tmp_path / 'unused-report.json')
    assert not (tmp_path / 'unused.onnx').exists()
