import copy
import json

import pytest

from deploy.cloud.original_libraries import MANIFEST, snapshot


def fixture():
    item = {'id': 'original', 'sha256': 'a'*64}
    row = {'id': 'first-library', 'name': 'Original creator', 'maintainer_id': 'creator-one',
        'url': 'https://github.com/creator-one/original',
        'rights_urls': ['https://github.com/creator-one/original/blob/abc/LICENSE'],
        'repository': 'https://github.com/creator-one/original', 'original_material': True,
        'verification': 'licensed-native-import-verified',
        'models': [{'channel': 'static', 'id': 'original', 'sha256': 'a'*64}]}
    document = {'version': 1, 'counting_rule': 'independent-original-libraries-v1', 'libraries': [row]}
    return document, [item]


def test_original_repository_counts_once_with_existing_reviewed_model():
    document, models = fixture()
    value = snapshot(document=document, static=models, runtime=[])
    assert value['verified_independent_sources'] == value['github_original_sources'] == 1
    assert value['network_requests'] == 0 and not value['target_complete']
    assert value['verified_libraries'][0]['one_click_verified']


@pytest.mark.parametrize('key,value', [('maintainer_id', 'creator-one'),
    ('repository', 'https://github.com/creator-one/original'), ('id', 'first-library')])
def test_duplicate_team_repo_or_source_cannot_increase_count(key, value):
    document, models = fixture()
    other = copy.deepcopy(document['libraries'][0])
    other.update(id='second-library', maintainer_id='other-team', repository='https://github.com/other-team/new')
    other[key] = value
    other['models'] = [{'channel': 'reviewed', 'id': 'other', 'sha256': 'b'*64}]
    document['libraries'].append(other)
    with pytest.raises(ValueError):
        snapshot(document=document, static=models, runtime=[{'id': 'other', 'sha256': 'b'*64}])


@pytest.mark.parametrize('update', [{'original_material': False}, {'verification': 'research'},
    {'models': []}, {'rights_urls': []}, {'repository': 'https://github.com/name/..'},
    {'url': 'https://user:secret@github.com/original/model'}])
def test_research_profiles_or_invalid_provenance_do_not_count(update):
    document, models = fixture()
    document['libraries'][0].update(update)
    with pytest.raises(ValueError):
        snapshot(document=document, static=models, runtime=[])


@pytest.mark.parametrize('ref', [{'channel': 'static', 'id': 'missing', 'sha256': 'a'*64},
    {'channel': 'static', 'id': 'original', 'sha256': 'b'*64},
    {'channel': 'unreviewed', 'id': 'original', 'sha256': 'a'*64}])
def test_link_without_admitted_binary_is_not_an_importable_source(ref):
    document, models = fixture()
    document['libraries'][0]['models'] = [ref]
    with pytest.raises(ValueError):
        snapshot(document=document, static=models, runtime=[])


def test_same_binary_cannot_be_recounted_under_another_creator():
    document, models = fixture()
    other = copy.deepcopy(document['libraries'][0])
    other.update(id='mirror', maintainer_id='other-team', repository='https://github.com/other/mirror')
    document['libraries'].append(other)
    with pytest.raises(ValueError):
        snapshot(document=document, static=models, runtime=[])


def test_actual_admitted_sources_and_hashes_are_cross_checked_without_downloads():
    value = snapshot()
    document = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert value['verified_independent_sources'] == len(document['libraries'])
    assert value['verified_independent_sources'] >= 8
    assert value['target_complete'] == (len(document['libraries']) >= 20)
    assert not value['mirrors_profiles_or_repeated_maintainers_counted']
