import hashlib
import io

import httpx
import pytest
from PIL import Image

from tools.cache_river_bottles import collect
from tools.prepare_river_bottles import BASE, COMMIT, REPO, TREE


def fixture():
    output = io.BytesIO()
    Image.new('RGB', (10, 10), 'blue').save(output, format='JPEG')
    raw = output.getvalue()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    row = {'source_group': '001-river', 'image_path': '001-river/a.jpg',
           'image_url': BASE + '001-river/a.jpg', 'image_git_blob': blob, 'image_bytes': len(raw),
           'width': 10, 'height': 10, 'status': 'metadata-ready'}
    return raw, {'source': f'https://github.com/{REPO}', 'commit': COMMIT, 'tree': TREE, 'items': [row]}


def test_cache_keeps_original_bytes_and_never_approves_training(tmp_path):
    raw, candidates = fixture()
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw))) as client:
        report = collect(candidates, tmp_path, client)
    assert report['cached_images'] == 1 and report['attempted_images'] == 1
    assert report['training_approved'] is False and report['formal_evaluation_eligible'] is False
    assert (tmp_path / (candidates['items'][0]['image_git_blob'] + '.jpg')).read_bytes() == raw


@pytest.mark.parametrize('change', ['hash', 'dimensions', 'url'])
def test_changed_or_untrusted_image_is_not_written(tmp_path, change):
    raw, candidates = fixture()
    row = candidates['items'][0]
    if change == 'hash':
        row['image_git_blob'] = 'a' * 40
    elif change == 'dimensions':
        row['width'] = 11
    else:
        row['image_url'] = 'https://untrusted.example/a.jpg'
    requests = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: (
            requests.append(request), httpx.Response(200, content=raw))[1])) as client:
        report = collect(candidates, tmp_path, client)
    assert report['cached_images'] == 0 and report['attempted_images'] == 1
    assert not list(tmp_path.glob('*.jpg'))
    if change == 'url':
        assert not requests


def test_cache_refuses_overwriting_an_existing_mismatched_file(tmp_path):
    raw, candidates = fixture()
    path = tmp_path / (candidates['items'][0]['image_git_blob'] + '.jpg')
    path.write_bytes(b'preserve me')
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw))) as client:
        report = collect(candidates, tmp_path, client)
    assert report['cached_images'] == 0 and path.read_bytes() == b'preserve me'


def test_total_budget_keeps_unavailable_candidate_in_denominator_without_request(tmp_path, monkeypatch):
    raw, candidates = fixture()
    monkeypatch.setattr('tools.cache_river_bottles.TOTAL_LIMIT', len(raw) - 1)
    requests = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: (
            requests.append(request), httpx.Response(200, content=raw))[1])) as client:
        report = collect(candidates, tmp_path, client)
    assert not requests and report['attempted_images'] == 1 and report['cached_images'] == 0
