import json

import pytest

from tools import inventory_commons_cups as tool


def page():
    return {'query': {'pages': [{'pageid': 1, 'title': 'File:Cup.jpg', 'imageinfo': [{
        'url': 'https://upload.wikimedia.org/wikipedia/commons/a/ab/Cup.jpg',
        'sha1': 'a' * 40, 'width': 100, 'height': 100, 'size': 1000, 'mime': 'image/jpeg',
        'extmetadata': {'Artist': {'value': '<b>Author</b>'}, 'LicenseShortName': {'value': 'CC BY 4.0'}}}]}]}}


def test_only_metadata_is_requested_and_rights_are_not_automatically_approved(monkeypatch):
    calls = []
    def fetch(client, url, **kwargs):
        calls.append((url, kwargs))
        return json.dumps(page()).encode()
    monkeypatch.setattr(tool, 'bounded_get', fetch)
    report = tool.inventory(None)
    assert len(calls) == 1 and calls[0][0] == tool.API
    assert report['listing_complete'] and report['images_downloaded'] == 0
    assert report['files'][0]['author_and_license_fields_present']
    assert not report['files'][0]['rights_cleared']
    assert not report['training_approved']


@pytest.mark.parametrize('case', ['url', 'warning', 'hash'])
def test_changed_or_untrusted_metadata_is_rejected(monkeypatch, case):
    payload = page()
    if case == 'warning':
        payload['warnings'] = {'imageinfo': 'property incomplete'}
    else:
        payload['query']['pages'][0]['imageinfo'][0]['url' if case == 'url' else 'sha1'] = 'untrusted'
    monkeypatch.setattr(tool, 'bounded_get', lambda *a, **k: json.dumps(payload).encode())
    with pytest.raises(ValueError):
        tool.inventory(None)


def test_paging_is_bounded_and_tokens_are_not_saved(monkeypatch):
    calls = []
    def fetch(*a, **kwargs):
        calls.append(kwargs)
        payload = page()
        payload['query']['pages'][0]['pageid'] = len(calls)
        payload['continue'] = {'continue': '-||', 'gcmcontinue': f'opaque{len(calls)}'}
        return json.dumps(payload).encode()
    monkeypatch.setattr(tool, 'bounded_get', fetch)
    report = tool.inventory(None)
    assert len(calls) == 3 and all(c['params']['gcmlimit'] == 5 for c in calls)
    assert report['listed_files'] == 3 and not report['listing_complete']
    assert 'opaque' not in json.dumps(report)


def test_malformed_attribution_is_rejected(monkeypatch):
    payload = page()
    payload['query']['pages'][0]['imageinfo'][0]['extmetadata']['Artist'] = 'not a field'
    monkeypatch.setattr(tool, 'bounded_get', lambda *a, **k: json.dumps(payload).encode())
    with pytest.raises(TypeError, match='attribution'):
        tool.inventory(None)
