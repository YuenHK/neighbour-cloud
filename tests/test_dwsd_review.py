import hashlib
import io
import json
import zipfile

import numpy as np
import pytest
from PIL import Image

from tools.review_dwsd_candidates import review


def fixture(tmp_path):
    path = tmp_path / 'source.zip'
    items = []
    with zipfile.ZipFile(path, 'w') as archive:
        for number in range(3):
            item = {'identity': f'Train/{number}'}
            for kind, directory, prefix in [('image', 'Image', 'img'), ('mask', 'Mask', 'mask')]:
                pixels = np.zeros((6, 8, 3), dtype=np.uint8) if kind == 'image' else np.zeros((6, 8), dtype=np.uint8)
                if kind == 'mask':
                    pixels[1:4, 2:6] = 11
                buffer = io.BytesIO()
                Image.fromarray(pixels).save(buffer, format='PNG')
                blob = buffer.getvalue()
                member = f'DSWD/Train/{directory}/{prefix}_{number}.png'
                archive.writestr(member, blob)
                item[kind], item[kind + '_sha256'] = member, hashlib.sha256(blob).hexdigest()
            items.append(item)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, {'archive_sha256': digest, 'paper_cup_candidates': items}, digest


def test_review_preserves_original_bytes_and_does_not_approve_alignment(tmp_path):
    path, audit, digest = fixture(tmp_path)
    output = tmp_path / 'review'
    result = review(path, json.dumps(audit).encode(), output, digest)
    assert len(result['results']) == 3
    for row in result['results']:
        assert row['paper_cup_union_xyxy'] == [2, 1, 6, 4]
        assert row['paper_cup_pixels'] == 12
        assert not row['alignment_verified']
        for kind in ('image', 'mask'):
            assert hashlib.sha256((output / row[kind + '_review_file']).read_bytes()).hexdigest() == row[kind + '_sha256']
    assert not result['training_approved']
    with pytest.raises(FileExistsError):
        review(path, json.dumps(audit).encode(), output, digest)


@pytest.mark.parametrize('change', ['path', 'hash'])
def test_untrusted_candidate_is_rejected_before_export(tmp_path, change):
    path, audit, digest = fixture(tmp_path)
    audit['paper_cup_candidates'][0]['image' if change == 'path' else 'image_sha256'] = '../outside.png'
    output = tmp_path / 'review'
    with pytest.raises(ValueError):
        review(path, json.dumps(audit).encode(), output, digest)
    assert not output.exists()
