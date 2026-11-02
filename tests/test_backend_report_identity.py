import hashlib
import json

import pytest

from tools import run_backend_acceptance as backend


def copied_fixture(root):
    source = root / 'code.py'
    source.write_bytes(b'original source')
    runtime = root / '.runtime'
    runtime.mkdir()
    (runtime / 'deployment-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'build_id': 'fixture-build',
        'files': {'code.py': hashlib.sha256(source.read_bytes()).hexdigest()}}), encoding='utf-8')
    return source


def test_report_captures_time_unique_run_and_stable_identity(tmp_path):
    copied_fixture(tmp_path)
    operation = lambda: {'passed': True, 'checks': {'synthetic': True}, 'hardware_acceptance': False}
    first = backend.run_recorded(tmp_path, operation)
    second = backend.run_recorded(tmp_path, operation)
    assert first['run_id'] != second['run_id'] and len(first['run_id']) == 32
    assert first['started_at_utc'] <= first['finished_at_utc']
    assert first['passed'] is True and first['software_identity_stable'] is True
    identity = first['software_identity_before']
    assert identity == first['software_identity_after']
    assert identity['build_id'] == 'fixture-build'
    assert len(identity['runner_source_sha256']) == 64
    assert set(identity['installed_packages']) == {'fastapi', 'starlette', 'httpx', 'pydantic', 'anyio'}
    assert first['hardware_acceptance'] is False


def test_unverified_inventory_blocks_before_operation(tmp_path):
    def forbidden():
        raise AssertionError('must not run without verified inventory')
    with pytest.raises(ValueError, match='verified copied inventory'):
        backend.run_recorded(tmp_path, forbidden)


def test_source_changed_during_run_cannot_claim_pass(tmp_path):
    source = copied_fixture(tmp_path)
    def operation():
        source.write_bytes(b'changed while checking')
        return {'passed': True, 'checks': {'synthetic': True}}
    report = backend.run_recorded(tmp_path, operation)
    assert report['checks'] == {'synthetic': True}
    assert report['software_identity_stable'] is False and report['passed'] is False
    assert report['software_identity_after']['disk_matches_manifest'] is False


def test_declared_dependency_drift_cannot_claim_pass(monkeypatch, tmp_path):
    identities = iter([{'disk_matches_manifest': True, 'version': 'a'},
                       {'disk_matches_manifest': True, 'version': 'b'}])
    monkeypatch.setattr(backend, 'software_identity', lambda root: next(identities))
    report = backend.run_recorded(tmp_path, lambda: {'passed': True})
    assert report['passed'] is False and report['software_identity_stable'] is False


def test_failed_checks_are_not_upgraded_by_stable_identity(tmp_path):
    copied_fixture(tmp_path)
    report = backend.run_recorded(tmp_path, lambda: {'passed': False, 'checks': {'failed': False}})
    assert report['software_identity_stable'] is True and report['passed'] is False


def test_replaced_manifest_with_same_build_label_is_not_same_identity(tmp_path):
    source = copied_fixture(tmp_path)
    manifest = tmp_path / '.runtime/deployment-manifest.json'
    def operation():
        source.write_bytes(b'different source and matching manifest')
        value = json.loads(manifest.read_text(encoding='utf-8'))
        value['files']['code.py'] = hashlib.sha256(source.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(value), encoding='utf-8')
        return {'passed': True}
    report = backend.run_recorded(tmp_path, operation)
    assert report['software_identity_after']['disk_matches_manifest'] is True
    assert report['software_identity_before']['build_id'] == report['software_identity_after']['build_id']
    assert report['software_identity_stable'] is False and report['passed'] is False
