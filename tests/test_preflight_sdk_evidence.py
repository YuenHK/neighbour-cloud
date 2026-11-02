import json
import platform
import sys
import sysconfig

import pytest

from tools import acceptance_preflight as preflight


def evidence(status='blocked_native_wheel_abi'):
    return {'status': status, 'python': f'{sys.version_info.major}.{sys.version_info.minor}',
            'platform': sysconfig.get_platform().replace('-', '_').replace('.', '_'),
            'python_implementation': platform.python_implementation()}


@pytest.mark.parametrize('status,expected', [
    ('blocked_native_wheel_abi', 'reported_blocked'),
    ('dependency_review_required', 'candidate_review_required'),
    ('artifact_checksum_review_required', 'candidate_review_required'),
])
def test_saved_report_is_not_installation_or_import_certificate(status, expected):
    sdk = evidence(status)
    sdk.update(sdk_installed=True, sdk_import_tested=True, hardware_acceptance=True,
               compatible_binary_available=True, checksum_recorded_candidate_available=True)
    report = preflight.assemble({}, {}, 0, None, sdk)
    summary = report['saved_sdk_report']
    assert summary['state'] == expected
    assert summary['target_binding_status'] == 'matches_runtime_metadata'
    assert summary['installed_verified'] is summary['import_verified'] is False
    assert summary['freshness_verified'] is False
    assert report['gates']['sdk_install_import'] is False
    assert report['complete_system_accepted'] is report['hardware_acceptance'] is False
    assert next(row for row in report['checklist'] if row['id'] == 'sdk')['state'] == 'not_verified'


@pytest.mark.parametrize('field', ['python', 'platform', 'python_implementation'])
def test_other_runtime_metadata_is_not_current_runtime_blocker(field):
    sdk = evidence()
    sdk[field] = 'different-private-target'
    report = preflight.saved_sdk_evidence(sdk)
    assert report['state'] == report['target_binding_status'] == 'different_runtime'
    assert 'private' not in json.dumps(report)


def test_invalid_status_is_allowlisted_not_echoed():
    sdk = evidence('private exception / token')
    sdk['compatible_binary_available'] = True
    report = preflight.saved_sdk_evidence(sdk)
    assert report['state'] == 'not_verified' and report['tag_candidate_reported'] is False
    assert 'private' not in json.dumps(report)


def test_sdk_report_is_explicit_read_only_and_never_auto_selected(tmp_path, monkeypatch):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    path = runtime / 'robomaster-sdk-preflight.json'
    raw = json.dumps(evidence()).encode()
    path.write_bytes(raw)
    monkeypatch.setattr('cv2.VideoCapture', lambda *a: pytest.fail('camera forbidden'))
    report = preflight.collect(tmp_path, offline=True)
    assert report['sdk_report_supplied'] is False
    assert report['saved_sdk_report']['present'] is False
    report = preflight.collect(tmp_path, offline=True, sdk_report=path)
    assert report['sdk_report_supplied'] is True
    assert report['saved_sdk_report']['state'] == 'reported_blocked'
    assert path.read_bytes() == raw
    assert list(tmp_path.rglob('*.sqlite3')) == []


def test_cli_passes_explicit_sdk_report_without_importing_sdk(tmp_path, monkeypatch):
    path = tmp_path / 'saved.json'
    seen = []

    def collect(root, **kwargs):
        seen.append(kwargs)
        return {'complete_system_accepted': False}

    monkeypatch.setattr(preflight, 'collect', collect)
    monkeypatch.setattr(sys, 'argv', ['preflight', '--offline', '--sdk-report', str(path)])
    assert preflight.main() == 2
    assert seen[0]['sdk_report'] == path and seen[0]['offline'] is True
