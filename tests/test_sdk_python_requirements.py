import platform
import sys
import sysconfig

import pytest

from tools.acceptance_preflight import saved_sdk_evidence
from tools.check_robomaster_sdk import assess


def metadata(project=None, wheel=None):
    return {'info': {'name': 'robomaster', 'requires_python': project}, 'urls': [{
        'filename': 'robomaster-1-cp312-cp312-win_amd64.whl',
        'requires_python': wheel, 'digests': {'sha256': 'a' * 64}}]}


@pytest.mark.parametrize('project,wheel,expected', [
    (None, None, 'dependency_review_required'),
    ('>=3.8,<3.13', '>=3.12.1', 'dependency_review_required'),
    ('<3.12', None, 'blocked_python_requirement'),
    (None, '<3.12', 'blocked_python_requirement'),
    ('>=3.12', '!=3.12.*', 'blocked_python_requirement'),
    ('invalid-private', None, 'invalid_python_requirement'),
    (None, '=>3.12', 'invalid_python_requirement'),
    (True, None, 'invalid_python_requirement'),
    (None, '>' * 1025, 'invalid_python_requirement'),
])
def test_project_and_wheel_python_constraints_both_apply(project, wheel, expected):
    report = assess(metadata(project, wheel), 3, 12, 'win_amd64', patch=10)
    assert report['status'] == expected
    assert report['python_full_version'] == '3.12.10'
    assert report['compatible_binary_available'] is True  # Tag only, not enough.
    assert report['checksum_recorded_candidate_available'] is True
    assert report['review_candidate_available'] is (expected == 'dependency_review_required')
    assert report['sdk_installed'] is report['sdk_import_tested'] is False


def test_patch_level_and_compatible_release_specifier():
    data = metadata('~=3.12.0', '>=3.12.10')
    assert not assess(data, 3, 12, 'win_amd64', patch=9)['review_candidate_available']
    assert assess(data, 3, 12, 'win_amd64', patch=10)['review_candidate_available']
    assert not assess(data, 3, 13, 'win_amd64', patch=0)['review_candidate_available']


def test_checksums_and_python_compatibility_must_belong_to_same_artifact():
    data = metadata(None, '<3.12')
    second = dict(data['urls'][0], requires_python='>=3.12', digests={})
    data['urls'].append(second)
    report = assess(data, 3, 12, 'win_amd64', patch=10)
    assert report['checksum_recorded_candidate_available'] is True
    assert report['python_compatible_candidate_available'] is True
    assert report['review_candidate_available'] is False
    assert report['status'] == 'artifact_checksum_review_required'


@pytest.mark.parametrize('status', ['blocked_python_requirement', 'invalid_python_requirement'])
def test_saved_sdk_preflight_recognizes_new_blocks_without_certifying_import(status):
    report = saved_sdk_evidence({'status': status})
    assert report['state'] == 'reported_blocked'
    assert report['installed_verified'] is report['import_verified'] is False


@pytest.mark.parametrize('matching', [False, True])
def test_saved_sdk_patch_target_is_compared_when_present(matching):
    version = f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
    report = saved_sdk_evidence({
        'status': 'dependency_review_required',
        'python': f'{sys.version_info.major}.{sys.version_info.minor}',
        'python_full_version': version if matching else '0.0.0',
        'platform': sysconfig.get_platform().replace('-', '_').replace('.', '_'),
        'python_implementation': platform.python_implementation(),
    })
    assert report['target_binding_status'] == ('matches_runtime_metadata' if matching else 'different_runtime')
