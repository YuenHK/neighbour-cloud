import json
import zipfile

import pytest

from tools.prepare_lvis_paper_cups import MEMBER, coco_image_url, prepare


def write_archive(path, *, bbox=None, duplicate=False):
    category = {'id': 377, 'name': 'Dixie_cup', 'synset': 'dixie_cup.n.01',
                'def': 'a disposable cup made of paper', 'synonyms': ['paper_cup']}
    data = {'categories': [category, category.copy()] if duplicate else [category],
            'images': [{'id': 7, 'width': 100, 'height': 80,
                        'coco_url': 'http://images.cocodataset.org/train2017/000000000007.jpg'}],
            'annotations': [{'id': 12, 'image_id': 7, 'category_id': 377,
                             'bbox': bbox if bbox is not None else [10, 20, 30, 40]},
                            {'id': 13, 'image_id': 7, 'category_id': 999, 'bbox': [0, 0, 5, 5]}]}
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MEMBER, json.dumps(data))


def test_official_subtype_and_boxes_retained_without_assigning_training_split(tmp_path):
    source = tmp_path / 'metadata.zip'
    write_archive(source)
    result = prepare(source)
    assert result['image_count'] == 1 and result['object_count'] == 1
    assert result['items'][0]['source_split'] == 'LVIS-v1-validation'
    assert result['items'][0]['split'] is None
    assert result['items'][0]['objects'][0]['bbox_xywh'] == [10., 20., 30., 40.]
    assert result['training_approved'] is False and result['images_downloaded'] == 0
    assert len(result['annotations_sha256']) == 64
    assert list(tmp_path.iterdir()) == [source]  # No extraction or image writes.


@pytest.mark.parametrize('url', ['https://evil.example/train2017/000000000007.jpg',
                                 'https://images.cocodataset.org/../private.jpg',
                                 'https://images.cocodataset.org/train2017/000000000007.jpg?key=x'])
def test_untrusted_image_url_is_not_forwarded(url):
    with pytest.raises(ValueError, match='COCO'):
        coco_image_url(url)


def test_duplicate_target_category_rejected(tmp_path):
    source = tmp_path / 'metadata.zip'
    write_archive(source, duplicate=True)
    with pytest.raises(ValueError, match='exactly one'):
        prepare(source)


def test_out_of_bounds_boxes_reported_not_silently_counted_as_usable(tmp_path):
    source = tmp_path / 'metadata.zip'
    write_archive(source, bbox=[95, 20, 30, 40])
    result = prepare(source)
    assert result['object_count'] == 0 and result['rejected_objects'] == [12]


def test_wrong_archive_member_is_never_extracted(tmp_path):
    source = tmp_path / 'metadata.zip'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('../' + MEMBER, '{}')
    with pytest.raises(ValueError, match='member'):
        prepare(source)
