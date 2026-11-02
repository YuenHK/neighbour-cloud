import json

import pytest

from tools import prepare_drinking_waste as tool


def metadata():
    return {'currentVersionNumber': 2, 'licenseName': 'CC0: Public Domain',
            'description': 'Aluminium Cans PET trashnet', 'totalBytes': 123}


def test_inventory_only_reads_bounded_metadata_and_keeps_gates_closed(monkeypatch):
    responses = [metadata(), {'datasetFiles': [
        {'name': 'Images_of_Waste/YOLO_imgs/AluCan1,000.jpg', 'totalBytes': 100},
        {'name': 'Images_of_Waste/YOLO_imgs/AluCan1,000.txt', 'totalBytes': 20}],
        'nextPageToken': 'opaque-page'}, {'datasetFiles': [], 'nextPageToken': 'another-page'}, metadata()]
    calls = []
    def fetch(client, url, **kwargs):
        calls.append((url, kwargs))
        return json.dumps(responses.pop(0)).encode()
    monkeypatch.setattr(tool, 'bounded_get', fetch)
    result = tool.inventory(None)
    assert len(calls) == 4
    assert all('/datasets/view/' in url or '/datasets/list/' in url for url, _ in calls)
    assert all(options['limit'] == 1024 * 1024 for _, options in calls)
    assert result['image_label_pairs_listed'] == 1
    assert result['listing_complete'] is False
    assert result['training_approved'] is result['formal_evaluation_eligible'] is False
    assert 'opaque-page' not in json.dumps(result)


@pytest.mark.parametrize('path', ['../bad.jpg', '/bad.jpg', 'C:/bad.jpg', 'a\\b.jpg'])
def test_unsafe_listing_paths_are_rejected(monkeypatch, path):
    responses = [metadata(), {'datasetFiles': [{'name': path, 'totalBytes': 1}]}]
    monkeypatch.setattr(tool, 'bounded_get', lambda *a, **k: json.dumps(responses.pop(0)).encode())
    with pytest.raises(ValueError, match='unsafe'):
        tool.inventory(None)


def test_changed_version_is_rejected_before_listing(monkeypatch):
    changed = {**metadata(), 'currentVersionNumber': 3}
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args)
        return json.dumps(changed).encode()
    monkeypatch.setattr(tool, 'bounded_get', fetch)
    with pytest.raises(ValueError, match='version'):
        tool.inventory(None)
    assert len(calls) == 1


@pytest.mark.parametrize('pages', [0, 129, True, 1.5])
def test_inventory_refuses_unbounded_page_counts(pages):
    with pytest.raises(ValueError, match='pages'):
        tool.inventory(None, pages)


def test_expanded_inventory_stops_at_end_and_finds_class_map(monkeypatch):
    responses = [metadata(), {'datasetFiles': [
        {'name': 'Images_of_Waste/labels.txt', 'totalBytes': 24}]}, metadata()]
    monkeypatch.setattr(tool, 'bounded_get', lambda *a, **k: json.dumps(responses.pop(0)).encode())
    result = tool.inventory(None, 128)
    assert result['listing_complete'] is True
    assert result['class_map_candidates'] == ['Images_of_Waste/labels.txt']
    assert result['label_class_mapping_verified'] is False
    assert result['label_files_downloaded'] == 0
    assert not responses
