import pytest

from tools.audit_litter_history_overlap import author_group, compare, read_cached_candidates


def record(sha='a', dhash='0000000000000000', **changes):
    return {'sha256': sha, 'dhash': dhash, 'low_detail': False, **changes}


def test_exact_and_near_matches_require_review_not_deletion_or_reassignment():
    result = compare({'1': record(), '2': record('b', '0000000000000001')},
                     {'old.jpg': record()}, set(), set())
    assert result['review_candidate_ids'] == ['1', '2']
    assert result['candidate_records']['1']['exact_paths'] == ['old.jpg']
    assert result['candidate_records']['2']['near_paths'][0]['distance'] == 1
    assert result['training_approved'] is False and result['images_deleted'] is False


def test_source_photo_or_author_overlap_not_hidden_by_different_file_hash():
    result = compare({'1': record('x', 'ffffffffffffffff', photo_id='123',
                                 author_url='https://www.flickr.com/photos/same/')}, {},
                     {'flickr:123'}, {'flickr:same'})
    assert result['review_candidate_ids'] == ['1']
    assert result['candidate_records']['1']['source_photo_overlap']
    assert result['candidate_records']['1']['author_overlap']


def test_author_people_and_photos_urls_are_same_conservative_group():
    assert author_group('https://www.flickr.com/people/Same/') == 'flickr:same'
    assert author_group('https://flickr.com/photos/Same/') == 'flickr:same'
    assert author_group('https://evil.example/photos/Same/') == ''


def test_missing_or_tampered_candidate_stays_in_review():
    result = compare({'7': {'error': 'hash_mismatch'}}, {}, set(), set())
    assert result['review_candidate_ids'] == ['7']
    assert result['candidate_records']['7']['error'] == 'hash_mismatch'


def test_no_detected_overlap_is_not_independence_or_model_acceptance():
    result = compare({'1': record('x', 'ffffffffffffffff')}, {}, set(), set())
    assert result['review_candidate_ids'] == []
    assert result['source_independence_verified'] is False
    assert result['formal_evaluation_eligible'] is False


def test_river_cache_uses_source_path_identity_without_inventing_flickr_provenance(monkeypatch):
    monkeypatch.setattr('tools.audit_litter_history_overlap.image_fingerprint', lambda _: record())
    result = read_cached_candidates({'items': [{'image_path': '001-river/a.jpg', 'source_group': '001-river',
        'path': 'unused.jpg', 'sha256': 'a', 'status': 'cached'},
        {'image_path': '002-river/b.jpg', 'status': 'unavailable'}]})
    assert list(result) == ['001-river/a.jpg']
    assert result['001-river/a.jpg']['source_group'] == '001-river'
    assert result['001-river/a.jpg']['photo_id'] == ''
    assert result['001-river/a.jpg']['author_url'] is None


def test_near_duplicates_within_candidates_require_review_even_without_historical_match():
    result = compare({'a': record('a', '0000000000000000'), 'b': record('b', '0000000000000001')},
                     {}, set(), set())
    assert result['review_candidate_ids'] == ['a', 'b']
    assert result['within_candidate_matches'][0]['distance'] == 1
    assert result['source_independence_verified'] is False


def test_duplicate_generic_candidate_identity_is_rejected(monkeypatch):
    monkeypatch.setattr('tools.audit_litter_history_overlap.image_fingerprint', lambda _: record())
    row = {'image_path': '001-river/a.jpg', 'path': 'unused.jpg', 'sha256': 'a', 'status': 'cached'}
    with pytest.raises(ValueError, match='duplicate'):
        read_cached_candidates({'items': [row, row]})
