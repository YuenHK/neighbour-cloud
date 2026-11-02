import io

import httpx
import pytest
from PIL import Image

from tools.cache_lvis_paper_cups import coco_download_url, collect, flickr_photo_id


def candidate():
    return {'image_id': 7, 'width': 10, 'height': 10, 'license': 4,
            'source_url': 'http://farm4.staticflickr.com/12/123456789_abc_z.jpg',
            'image_url': 'https://images.cocodataset.org/val2017/000000000007.jpg',
            'objects': [{'annotation_id': 12, 'bbox_xywh': [1, 1, 5, 5]}]}


def transport(*, license_id='4', corrupt=False):
    buffer = io.BytesIO()
    Image.new('RGB', (10, 10), 'white').save(buffer, format='JPEG')

    def reply(request):
        assert request.headers['User-Agent'] == 'Zhiwei-Public-Dataset-Research/1.0'
        if request.url.host == 'www.flickr.com':
            return httpx.Response(200, json={'author_name': 'Author', 'author_url': 'https://www.flickr.com/photos/author/',
                'web_page': 'https://www.flickr.com/photos/author/123456789/', 'title': 'Public example',
                'license_id': license_id, 'license_url': 'https://creativecommons.org/licenses/by/2.0/',
                'html': '<script>never retain this</script>'})
        return httpx.Response(200, content=b'not a picture' if corrupt else buffer.getvalue())
    return httpx.MockTransport(reply)


def test_provenance_verified_before_public_download_and_no_html_or_training(tmp_path):
    with httpx.Client(transport=transport()) as client:
        result = collect({'items': [candidate()]}, tmp_path, client)
    assert result['cached_images'] == 1 and result['attempted_images'] == 1
    item = result['items'][0]
    assert len(item['sha256']) == 64 and item['author_name'] == 'Author'
    assert 'html' not in str(result)
    assert result['training_approved'] is False and not result['formal_evaluation_eligible']


def test_license_change_blocks_image_request_and_preserves_failure_in_denominator(tmp_path):
    with httpx.Client(transport=transport(license_id='6')) as client:
        result = collect({'items': [candidate()]}, tmp_path, client)
    assert result['cached_images'] == 0 and result['attempted_images'] == 1
    assert result['items'][0]['status'] == 'failed'
    assert not list(tmp_path.glob('*.jpg'))


@pytest.mark.parametrize('url', ['https://evil.example/123456789_abc.jpg',
                                 'https://farm4.staticflickr.com:444/12/123456789_abc.jpg',
                                 'https://farm4.staticflickr.com/12/abc_xyz.jpg'])
def test_untrusted_source_url_does_not_become_network_target(url):
    with pytest.raises(ValueError):
        flickr_photo_id(url)


def test_corrupt_response_never_creates_accepted_image(tmp_path):
    with httpx.Client(transport=transport(corrupt=True)) as client:
        result = collect({'items': [candidate()]}, tmp_path, client)
    assert result['cached_images'] == 0 and result['items'][0]['status'] == 'failed'
    assert not list(tmp_path.glob('*.jpg'))


def test_http_failure_records_stage_and_code_without_response_body(tmp_path):
    mock = httpx.MockTransport(lambda request: httpx.Response(503, text='do not retain response content'))
    with httpx.Client(transport=mock) as client:
        result = collect({'items': [candidate()]}, tmp_path, client)
    assert result['items'][0]['http_status'] == 503
    assert result['items'][0]['failed_stage'] == 'source-metadata'
    assert 'response content' not in str(result)


def test_coco_download_uses_same_bucket_with_valid_tls_not_insecure_fallback():
    assert coco_download_url(candidate()['image_url']) == (
        'https://s3.amazonaws.com/images.cocodataset.org/val2017/000000000007.jpg')
    with pytest.raises(ValueError):
        coco_download_url('https://evil.example/val2017/000000000007.jpg')
