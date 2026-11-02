import json

import pytest

from tools.group_dwsd_candidates import components, group_candidates


def test_transitive_candidates_group_without_claiming_independence():
    identities = ['Train/1', 'Test/2', 'Train/3', 'Test/4']
    pairs = [{'a': 'Train/1', 'b': 'Test/2', 'geometry_overlap_candidate': True},
             {'a': 'Test/2', 'b': 'Train/3', 'geometry_overlap_candidate': True},
             {'a': 'Train/3', 'b': 'Test/4', 'geometry_overlap_candidate': False}]
    result = components(identities, pairs)
    assert len(result) == 2
    merged = next(g for g in result if len(g['items']) == 3)
    assert merged['cross_upstream_split']
    assert all(not g['is_verified_independent_source'] for g in result)
    assert identities == ['Train/1', 'Test/2', 'Train/3', 'Test/4']


@pytest.mark.parametrize('count', [0, 1, 31])
def test_unbounded_candidates_rejected_before_archive_access(tmp_path, count):
    from tools.cache_dwsd import SHA256
    metadata = {'archive_sha256': SHA256,
                'paper_cup_candidates': [{'identity': f'Train/{i}'} for i in range(count)]}
    with pytest.raises(ValueError, match='budget'):
        group_candidates(tmp_path / 'does-not-exist.zip', json.dumps(metadata).encode())
