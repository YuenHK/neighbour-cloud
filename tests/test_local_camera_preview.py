import json

import httpx
import numpy as np

from edge_hub.vision import Detection
from tools.local_camera_preview import DetectionPreview, PAGE, start_preview


def test_annotations_are_separate_ram_copy_with_labels_and_confirmation():
    raw = np.zeros((120, 160, 3), dtype=np.uint8)
    bottle = Detection('plastic_bottle', 0.9, (10, 20, 30, 60))
    package = Detection('paper_ball_package', 0.7, (80, 50, 30, 30))
    overlay = DetectionPreview()
    overlay.update(raw, [bottle, package], [bottle], 'bottle')
    image, metadata = overlay.snapshot()
    assert not raw.any()
    assert image.any()
    assert metadata['snapshot_not_live']
    assert metadata['detections'][0]['confirmed_in_this_sample']
    assert not metadata['detections'][1]['confirmed_in_this_sample']
    assert metadata['detections'][1]['name'] == '紙團／小包裝'
    image[:] = 0
    assert overlay.snapshot()[0].any()


def test_preview_is_loopback_no_store_and_rejects_cross_site():
    class Camera:
        annotations = DetectionPreview()

        def frame(self):
            return 42, None

    # port 0 selects a test port; the Host guard still deliberately accepts only configured hosts.
    server = start_preview(Camera(), 0)
    address = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with httpx.Client(trust_env=False) as client:
            result = client.get(address + '/status', headers={'Host': '127.0.0.1:0'})
            assert result.status_code == 200
            assert json.loads(result.text)['images_saved'] == 0
            assert result.headers['Cache-Control'].startswith('no-store')
            assert client.get(address + '/detections', headers={'Host': '127.0.0.1:0'}).json()['ready'] is False
            assert client.get(address + '/detections', headers={
                'Host': '127.0.0.1:0', 'Sec-Fetch-Site': 'cross-site',
            }).status_code == 403
            assert client.get(address + '/status', headers={
                'Host': '127.0.0.1:0', 'Sec-Fetch-Site': 'cross-site',
            }).status_code == 403
            assert client.get(address + '/status', headers={'Host': 'evil.example'}).status_code == 403
            landing = client.get(address + '/', headers={
                'Host': '127.0.0.1:0', 'Sec-Fetch-Site': 'cross-site',
            })
            assert landing.status_code == 200
            assert landing.headers['X-Frame-Options'] == 'DENY'
    finally:
        server.shutdown()
        server.server_close()
    assert 'https://' not in PAGE
    assert 'localStorage' not in PAGE
