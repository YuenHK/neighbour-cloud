import json

import pytest

from tools.cache_dwsd import SHA256
from tools.reconcile_dwsd_semantics import reconcile


def source():
    return {'archive_sha256': SHA256, 'decoded_pairs': 1,
            'records': {'Train/1': {'mask_values': [0, 11, 15], 'Image': 'original.png',
                                   'Mask': 'mask.png', 'image_sha256': 'a' * 64, 'mask_sha256': 'b' * 64}},
            'mask_value_image_counts': {'0': 1, '11': 1, '15': 1},
            'incomplete_pairs': [], 'decode_failures': {}}


def test_documented_background_does_not_approve_data_or_change_input():
    data = source()
    raw = json.dumps(data).encode()
    result = reconcile(raw)
    assert result['documented_labels']['15'] == 'Background'
    assert result['documented_labels']['11'] == 'Paper-cup'
    assert result['paper_cup_candidate_images'] == 1
    assert result['paper_cup_candidates'][0]['identity'] == 'Train/1'
    assert result['values_outside_author_table'] == []
    assert not result['training_approved'] and not result['mask_palette_verified']
    assert json.dumps(data).encode() == raw


def test_unknown_mask_value_is_preserved_not_mapped_to_background():
    data = source()
    data['records']['Train/1']['mask_values'].append(16)
    data['mask_value_image_counts']['16'] = 1
    assert reconcile(json.dumps(data).encode())['values_outside_author_table'] == [16]


@pytest.mark.parametrize('change', ['archive', 'count', 'presence', 'boolean'])
def test_inconsistent_audit_is_rejected(change):
    data = source()
    if change == 'archive':
        data['archive_sha256'] = '0' * 64
    elif change == 'count':
        data['decoded_pairs'] = 2
    elif change == 'presence':
        data['mask_value_image_counts']['15'] = 2
    else:
        data['records']['Train/1']['mask_values'] = [True]
    with pytest.raises(ValueError):
        reconcile(json.dumps(data).encode())
