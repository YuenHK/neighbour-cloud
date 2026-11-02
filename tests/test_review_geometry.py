import json

import cv2
import numpy as np
import pytest

from tools.check_review_geometry import check, compare


def test_rotated_texture_has_geometric_overlap_without_modifying_input():
    image = np.random.default_rng(12).integers(0, 256, (448, 448), dtype=np.uint8)
    original = image.copy()
    matrix = cv2.getRotationMatrix2D((224, 224), 25, 0.95)
    rotated = cv2.warpAffine(image, matrix, (448, 448))
    result = compare(image, rotated)
    assert result['geometry_overlap_candidate']
    assert result['inliers'] >= 20
    assert np.array_equal(original, image)


def test_blank_and_independent_textures_do_not_pass():
    blank = np.zeros((100, 100), np.uint8)
    assert not compare(blank, blank)['geometry_overlap_candidate']
    rng = np.random.default_rng(3)
    assert not compare(rng.integers(0, 256, (300, 300), dtype=np.uint8),
                       rng.integers(0, 256, (300, 300), dtype=np.uint8))['geometry_overlap_candidate']


@pytest.mark.parametrize('image', [np.zeros((2, 2), np.float32), np.zeros((2, 2, 3), np.uint8)])
def test_invalid_images_are_rejected(image):
    with pytest.raises(ValueError):
        compare(image, image)


def test_unbound_review_image_is_rejected(tmp_path):
    path = tmp_path / 'review.json'
    rows = [{'identity': str(i), 'image_review_file': 'image.png', 'image_sha256': '0' * 64}
            for i in range(3)]
    path.write_text(json.dumps({'results': rows}), encoding='utf-8')
    (tmp_path / 'image.png').write_bytes(b'not the reviewed bytes')
    with pytest.raises(ValueError, match='hash'):
        check(path)
