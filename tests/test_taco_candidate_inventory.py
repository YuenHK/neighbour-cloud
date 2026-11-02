import pytest

from tools.inventory_taco_candidates import inventory, photo_id


def fixture_data():
    return {'images': [{'id': 1, 'file_name': 'batch_1/a.jpg',
                        'flickr_url': 'https://farm1.staticflickr.com/12/123_abc.jpg'},
                       {'id': 2, 'file_name': 'batch_1/b.jpg'},
                       {'id': 3, 'file_name': 'batch_2/c.jpg'},
                       {'id': 4, 'file_name': 'batch_3/d.jpg',
                        'flickr_url': 'https://farm2.staticflickr.com/12/123_xyz.jpg'}],
            'categories': [{'id': 7, 'name': 'Paper cup'}, {'id': 8, 'name': 'Normal paper'}],
            'annotations': [{'image_id': index, 'category_id': 7} for index in range(1, 5)]
                           + [{'image_id': 3, 'category_id': 8}]}


def test_excludes_known_image_batch_and_photo_without_resplitting():
    manifest = {'items': [{'source_image': 'batch_1\\a.jpg', 'split': 'test'}]}
    result = inventory(fixture_data(), manifest)
    assert [item['status'] for item in result['items']] == [
        'already_used', 'same_batch', 'unseen_batch_candidate', 'same_photo']
    assert all(item['split'] is None for item in result['items'])
    assert result['counts_by_class']['paper_cup']['unseen_batch_candidate_objects'] == 1
    assert 'paper_ball_package' not in result['counts_by_class']
    assert result['training_approved'] is False
    assert manifest['items'][0]['split'] == 'test'


@pytest.mark.parametrize('name', ['../escape.jpg', '/root.jpg', 'C:/a.jpg'])
def test_rejects_unsafe_metadata_filename(name):
    data = fixture_data()
    data['images'][0]['file_name'] = name
    with pytest.raises(ValueError, match='unsafe'):
        inventory(data, {'items': []})


def test_rejects_duplicate_id_and_extracts_only_flickr_identity():
    data = fixture_data()
    data['images'].append(data['images'][0].copy())
    with pytest.raises(ValueError, match='duplicate'):
        inventory(data, {'items': []})
    assert photo_id('https://evilstaticflickr.com/12/123_abc.jpg') is None
    assert photo_id('http://farm1.staticflickr.com/12/123_abc.jpg') is None


def test_union_of_historical_manifests_prevents_reusing_quarantined_sources():
    result = inventory(fixture_data(), [
        {'items': [{'source_image': 'batch_1/a.jpg'}]},
        {'items': [{'source_image': 'batch_2/c.jpg', 'split': 'old-quarantine'}]}])
    assert result['used_source_images'] == 2
    assert result['items'][2]['status'] == 'already_used'


def test_dangling_annotation_cannot_silently_drop_from_inventory():
    data = fixture_data()
    data['annotations'].append({'image_id': 99, 'category_id': 7})
    with pytest.raises(ValueError, match='missing image'):
        inventory(data, {'items': []})
