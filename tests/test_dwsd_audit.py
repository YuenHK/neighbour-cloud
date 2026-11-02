import hashlib
import io
import zipfile

import numpy as np
import pytest
from PIL import Image

from tools.audit_dwsd import audit, pair_members, transform_pixel_hash


def png(array):
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format='PNG')
    return buffer.getvalue()


def test_audit_keeps_unknown_mask_values_and_cross_split_duplicates(tmp_path):
    path = tmp_path / 'data.zip'
    image = png(np.zeros((4, 4, 3), dtype=np.uint8))
    mask = png(np.full((4, 4), 15, dtype=np.uint8))
    with zipfile.ZipFile(path, 'w') as archive:
        for split in ('Train', 'Test'):
            archive.writestr(f'DSWD/{split}/Image/img_1.png', image)
            archive.writestr(f'DSWD/{split}/Mask/mask_1.png', mask)
    result = audit(path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert result['decoded_pairs'] == 2
    assert result['mask_value_image_counts'] == {'15': 2}
    assert result['values_outside_documented_0_to_14'] == [15]
    assert result['exact_rgb_pixel_groups'][0]['cross_upstream_split']
    assert not result['training_approved'] and not result['mask_palette_verified']
    assert not (tmp_path / 'DSWD').exists()


def test_incomplete_pair_stays_in_requested_denominator(tmp_path):
    path = tmp_path / 'data.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('DSWD/Train/Image/img_1.png', b'unpaired')
    result = audit(path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert result['requested_pairs'] == 1 and result['decoded_pairs'] == 0
    assert result['incomplete_pairs'] == ['Train/1']


def test_ambiguous_ids_and_changed_archive_are_rejected(tmp_path):
    with pytest.raises(ValueError, match='ambiguous'):
        pair_members(['DSWD/Train/Image/img_1.png', 'DSWD/Train/Image/img_01.png'])
    path = tmp_path / 'wrong.zip'
    path.write_bytes(b'not the pinned source')
    with pytest.raises(ValueError, match='hash mismatch'):
        audit(path)


def test_transform_hash_matches_exact_rotations_and_mirrors_not_changed_pixels():
    pixels = np.arange(6 * 4 * 3, dtype=np.uint8).reshape(4, 6, 3)
    original = transform_pixel_hash(Image.fromarray(pixels))
    assert transform_pixel_hash(Image.fromarray(np.rot90(pixels))) == original
    assert transform_pixel_hash(Image.fromarray(np.fliplr(pixels))) == original
    changed = pixels.copy()
    changed[0, 0, 0] ^= 1
    assert transform_pixel_hash(Image.fromarray(changed)) != original


def test_transform_groups_detect_cross_split_equivalence_without_changing_pairs(tmp_path):
    path = tmp_path / 'data.zip'
    pixels = np.arange(48, dtype=np.uint8).reshape(4, 4, 3)
    mask = png(np.zeros((4, 4), dtype=np.uint8))
    with zipfile.ZipFile(path, 'w') as archive:
        for split, image in [('Train', pixels), ('Test', np.rot90(pixels))]:
            archive.writestr(f'DSWD/{split}/Image/img_1.png', png(image))
            archive.writestr(f'DSWD/{split}/Mask/mask_1.png', mask)
    result = audit(path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert not result['exact_rgb_pixel_groups']
    assert result['rotation_mirror_groups'][0]['cross_upstream_split']
    assert result['upstream_pairs_by_split'] == {'Train': 1, 'Test': 1}
    assert not result['source_groups_verified']
