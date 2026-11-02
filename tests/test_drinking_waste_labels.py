import json
from unittest.mock import MagicMock
from urllib.parse import unquote

import pytest

from tools.audit_drinking_waste_labels import checked_storage_url, parse_yolo


def test_audit_preserves_bad_original_annotation_without_fixing_or_approving(monkeypatch):
    from tools import audit_drinking_waste_labels as tool

    raw = b'0 0.1 0.1 0.9 0.9\n'
    metadata = {'version': 2, 'platform_license': 'CC0: Public Domain', 'files': [
        {'name': f'Images_of_Waste/YOLO_imgs/{name}.txt', 'bytes': len(raw)} for name in 'abc']}
    class Client:
        def stream(self, method, url, **kwargs):
            path = unquote(url.split(tool.DATASET + '/')[1])
            response = MagicMock(status_code=302, headers={
                'location': 'https://storage.googleapis.com/kagglesdsdata/datasets/621064/1145779/' + path})
            context = MagicMock()
            context.__enter__.return_value = response
            return context
    monkeypatch.setattr(tool, 'bounded_get', lambda *args, **kwargs: raw)
    result = tool.audit(Client(), json.dumps(metadata).encode())
    assert result['requested'] == result['text_files_downloaded'] == 3
    assert result['valid_annotations'] == 0
    assert all(row['raw_text'] == raw.decode() and row['valid'] is False for row in result['results'])
    assert result['training_approved'] is False


def test_yolo_numeric_ids_remain_numeric_not_assumed_aluminium():
    assert parse_yolo(b'2 0.5 0.5 0.2 0.4\n')[0] == {
        'class_id': 2, 'bbox_cxcywh_normalized': [.5, .5, .2, .4]}


@pytest.mark.parametrize('raw', [b'0 nan 0.5 0.2 0.2', b'0 0.1 0.1 0.9 0.9',
                                b'-1 0.5 0.5 0.2 0.2', b'0 0.5 0.5 0 0.2'])
def test_invalid_text_does_not_become_valid_annotation(raw):
    with pytest.raises(ValueError):
        parse_yolo(raw)


def test_only_observed_versioned_storage_object_is_allowed():
    path = 'Images_of_Waste/YOLO_imgs/AluCan1,000.txt'
    valid = 'https://storage.googleapis.com:443/kagglesdsdata/datasets/621064/1145779/' + path
    assert checked_storage_url(valid + '?opaque=not-saved', path) == valid + '?opaque=not-saved'
    for changed in (valid.replace('https:', 'http:'), valid.replace('storage.googleapis.com', 'other.example'),
                    valid.replace('1145779', '1145780'), valid.replace('.txt', '.jpg')):
        with pytest.raises(ValueError):
            checked_storage_url(changed, path)
