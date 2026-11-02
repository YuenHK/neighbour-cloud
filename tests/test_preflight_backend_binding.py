import json

import pytest

from tools import acceptance_preflight as preflight


def fixture_report():
    identity = {'build_id': 'a' * 64, 'disk_matches_manifest': True}
    return {'mode': 'isolated-backend-software-simulation', 'passed': True,
            'checks': {'fixture': True}, 'software_identity_stable': True,
            'software_identity_before': identity, 'software_identity_after': dict(identity),
            'private-field': 'do-not-echo'}


@pytest.mark.parametrize('case,expected', [
    ('matching', 'matches_copied_build'), ('different', 'different_build'),
    ('disk-unverified', 'copied_files_unverified'), ('failed', 'not_passed'),
    ('empty-checks', 'not_passed'), ('legacy', 'unbound_report'),
    ('changed', 'identity_changed_or_unverified'), ('unstable', 'identity_changed_or_unverified'),
    ('wrong-mode', 'unbound_report'), ('missing', 'missing'),
])
def test_saved_backend_identity_is_only_a_reported_version_comparison(case, expected):
    backend = fixture_report()
    deployment = {'files': {'disk_matches_manifest': True, 'build_id': 'a' * 64},
                  'live_identity_matches': True}
    if case == 'different':
        deployment['files']['build_id'] = 'b' * 64
    elif case == 'disk-unverified':
        deployment['files']['disk_matches_manifest'] = False
    elif case == 'failed':
        backend['checks']['fixture'] = False
    elif case == 'empty-checks':
        backend['checks'] = {}
    elif case == 'legacy':
        backend = {'passed': True, 'checks': {'fixture': True}}
    elif case == 'changed':
        backend['software_identity_after']['build_id'] = 'b' * 64
    elif case == 'unstable':
        backend['software_identity_stable'] = False
    elif case == 'wrong-mode':
        backend['mode'] = 'other'
    elif case == 'missing':
        backend = None
    report = preflight.assemble(deployment, {'litter_model_accepted': True,
                                           'person_privacy_accepted': True}, 123, backend)
    evidence = report['saved_backend_report']
    assert evidence['version_binding_status'] == expected
    assert evidence['reported_identity_matches_copied_files'] is (case == 'matching')
    assert evidence['freshness_verified'] is False
    assert report['ready_to_schedule_field_acceptance'] is False
    assert report['complete_system_accepted'] is False and report['hardware_acceptance'] is False
    assert 'do-not-echo' not in json.dumps(report)


def test_collect_can_explicitly_select_report_without_overwriting_default(tmp_path, monkeypatch):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    default = runtime / 'backend-acceptance.json'
    original = json.dumps({'passed': False})
    default.write_text(original, encoding='utf-8')
    selected = tmp_path / 'selected-report.json'
    selected.write_text(json.dumps(fixture_report()), encoding='utf-8')
    monkeypatch.setattr(preflight, 'check_deployment', lambda *args, **kwargs: {
        'files': {'disk_matches_manifest': True, 'build_id': 'a' * 64}})
    report = preflight.collect(tmp_path, offline=True, backend_report=selected)
    assert report['saved_backend_report']['version_binding_status'] == 'matches_copied_build'
    assert preflight.collect(tmp_path, offline=True)['saved_backend_report']['claims_passed'] is False
    assert default.read_text(encoding='utf-8') == original
    assert report['services_modified'] is False and report['camera_opened'] is False
    assert 'selected-report' not in json.dumps(report)  # Local paths are not added to the report.


def test_deep_report_is_invalid_without_crashing_or_rewriting(tmp_path):
    path = tmp_path / 'report.json'
    raw = b'[' * 20_000 + b'0' + b']' * 20_000
    path.write_bytes(raw)
    assert preflight.read_object(path) is None
    assert path.read_bytes() == raw


def test_cli_forwards_explicit_report_and_keeps_non_acceptance_exit(monkeypatch, tmp_path):
    import sys

    selected = tmp_path / 'selected.json'
    seen = []
    monkeypatch.setattr(sys, 'argv', ['preflight', '--root', str(tmp_path), '--offline',
                                    '--backend-report', str(selected)])
    def collect(root, **kwargs):
        seen.append((root, kwargs))
        return {'complete_system_accepted': False}
    monkeypatch.setattr(preflight, 'collect', collect)
    assert preflight.main() == 2
    assert seen == [(tmp_path, {'offline': True, 'backend_report': selected})]


def test_uncomparable_nested_identity_never_claims_binding():
    backend = fixture_report()
    class Uncomparable(dict):
        def __eq__(self, other):
            raise RecursionError('synthetic comparison depth failure')
    backend['software_identity_before'] = Uncomparable(backend['software_identity_before'])
    evidence = preflight.saved_backend_evidence(backend, {
        'files': {'disk_matches_manifest': True, 'build_id': 'a' * 64}})
    assert evidence['version_binding_status'] == 'identity_changed_or_unverified'
    assert evidence['reported_identity_matches_copied_files'] is False
