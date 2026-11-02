import hashlib
import json
import sys

import pytest
from fastapi.testclient import TestClient

from edge_hub import app as hub
from edge_hub.ep_runtime_evidence import SDK_COMMIT, VERSIONS, runtime_evidence


def fixture_report(root):
    adapters = root / 'ep_runtime'
    sources = root / '.runtime/ep-sdk/source/src/robomaster'
    adapters.mkdir(parents=True)
    sources.mkdir(parents=True)
    (adapters / 'adapter.py').write_bytes(b'# synthetic adapter fixture')
    (sources / 'robot.py').write_bytes(b'# synthetic SDK fixture')
    report = {
        'schema': 'ep-isolated-runtime-probe-v1',
        'status': 'adapted_import_and_synthetic_codecs_passed',
        'runtime_kind': 'project_adapted_official_source_not_original_wheel',
        'sdk_source_commit': SDK_COMMIT, 'versions': VERSIONS,
        'python': '.'.join(map(str, sys.version_info[:3])),
        'source_pristine': True, 'sdk_import_tested': True, 'socket_guard_verified': True,
        'robot_initialized': False, 'robot_contacted': False, 'hardware_acceptance': False,
        'live_video_verified': False, 'live_audio_verified': False, 'live_control_verified': False,
        'synthetic_h264_frames': 3, 'synthetic_opus_packets': 2,
        'wheels': [{'filename': name.replace('-', '_') + '-' + version + '-fixture.whl',
                    'pypi_hash_matches': True, 'sha256': 'a' * 64} for name, version in VERSIONS.items()],
        'adapter_sha256': {'adapter.py': hashlib.sha256((adapters / 'adapter.py').read_bytes()).hexdigest()},
        'sdk_source_sha256': {'robot.py': hashlib.sha256((sources / 'robot.py').read_bytes()).hexdigest()},
        'private': 'never-return-private-values',
    }
    return report


def write_report(root, data):
    (root / '.runtime/ep-sdk/validated-runtime.json').write_text(json.dumps(data), encoding='utf-8')


def test_valid_local_evidence_is_reported_but_cannot_enable_hardware(monkeypatch, tmp_path):
    data = fixture_report(tmp_path)
    write_report(tmp_path, data)
    assert runtime_evidence(tmp_path) == 'reported_offline_pass'
    monkeypatch.setattr(hub, 'PROJECT_ROOT', tmp_path)
    client = TestClient(hub.app)
    path = '/api/v1/robot/ep/preparation'
    assert client.get(path).status_code == 403
    response = client.get(path, headers={'X-Operator-Key': 'unit-test-operator-only'})
    assert response.json()['adapted_runtime_report_state'] == 'reported_offline_pass'
    assert all(response.json()[key] is False for key in
               ('motion_enabled', 'video_enabled', 'audio_enabled', 'hardware_acceptance'))
    assert 'never-return-private-values' not in response.text
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('key,value', [
    ('robot_initialized', True), ('robot_contacted', True), ('hardware_acceptance', True),
    ('live_video_verified', True), ('source_pristine', 'true'), ('sdk_import_tested', 1),
    ('sdk_source_commit', 'wrong'), ('python', '3.8.0'), ('synthetic_h264_frames', True),
    ('synthetic_opus_packets', 0), ('synthetic_opus_packets', False),
])
def test_invalid_or_hardware_claiming_evidence_is_rejected(tmp_path, key, value):
    data = fixture_report(tmp_path)
    data[key] = value
    write_report(tmp_path, data)
    assert runtime_evidence(tmp_path) == 'incompatible_or_stale'


def test_adapter_or_sdk_source_drift_invalidates_evidence(tmp_path):
    data = fixture_report(tmp_path)
    write_report(tmp_path, data)
    (tmp_path / 'ep_runtime/adapter.py').write_bytes(b'# changed after probe')
    assert runtime_evidence(tmp_path) == 'incompatible_or_stale'


@pytest.mark.parametrize('case', ['offline', 'duplicate', 'hash'])
def test_unverified_or_ambiguous_wheel_provenance_is_rejected(tmp_path, case):
    data = fixture_report(tmp_path)
    if case == 'offline':
        data['wheels'][0]['pypi_hash_matches'] = None
    elif case == 'duplicate':
        data['wheels'][1] = data['wheels'][0]
    else:
        data['wheels'][0]['sha256'] = 'bad'
    write_report(tmp_path, data)
    assert runtime_evidence(tmp_path) == 'incompatible_or_stale'


def test_missing_or_malformed_report_is_not_a_pass(tmp_path):
    assert runtime_evidence(tmp_path) == 'unavailable'
    fixture_report(tmp_path)
    (tmp_path / '.runtime/ep-sdk/validated-runtime.json').write_bytes(b'not JSON')
    assert runtime_evidence(tmp_path) == 'unavailable'
