import hashlib
import json
from pathlib import Path

import pytest

from edge_hub.deployment import loaded_identity, verify_files


def test_inventory_and_startup_hash_files_without_whole_file_reads(tmp_path, monkeypatch):
    app = tmp_path / 'edge_hub/app.py'
    app.parent.mkdir()
    raw = b'multi-chunk fixture\r\n' * 130_000
    app.write_bytes(raw)
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    (runtime / 'deployment-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'build_id': 'chunked',
        'files': {'edge_hub/app.py': hashlib.sha256(raw).hexdigest()}}), encoding='utf-8')
    def forbidden(*args, **kwargs):
        raise AssertionError('whole-file read is not a bounded hash')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    assert verify_files(tmp_path)['disk_matches_manifest']
    assert loaded_identity(tmp_path)['build_id'] == 'chunked'


def test_file_hash_uses_fixed_chunks_and_preserves_raw_bytes(tmp_path, monkeypatch):
    import io

    from edge_hub.deployment import file_sha256

    raw = b'\x00\xff\r\n' * 600_000
    sizes = []
    class Reader(io.BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            assert size == 1024 * 1024
            return super().read(size)
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: Reader(raw))
    assert file_sha256(tmp_path / 'fixture') == hashlib.sha256(raw).hexdigest()
    assert len(sizes) == 4  # Three data chunks followed by EOF.


def test_manifest_read_has_actual_byte_cap_not_only_prior_stat(tmp_path, monkeypatch):
    import io

    raw = b' ' * 2_000_010
    sizes = []
    class Reader(io.BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            assert size == 2_000_001
            return super().read(size)
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: Reader(raw))
    assert verify_files(tmp_path) == {'status': 'invalid_manifest', 'disk_matches_manifest': False}
    assert sizes == [2_000_001]


def test_deeply_nested_manifest_fails_closed_in_verifier_and_startup(tmp_path):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    manifest = runtime / 'deployment-manifest.json'
    raw = b'[' * 20_000 + b'0' + b']' * 20_000
    manifest.write_bytes(raw)
    app = tmp_path / 'edge_hub/app.py'
    app.parent.mkdir()
    app.write_bytes(b'fixture')
    assert verify_files(tmp_path) == {'status': 'invalid_manifest', 'disk_matches_manifest': False}
    assert loaded_identity(tmp_path)['build_id'] is None
    assert manifest.read_bytes() == raw  # Do not repair or overwrite rejected evidence.


def test_bom_manifest_keeps_existing_digest_semantics(tmp_path):
    app = tmp_path / 'edge_hub/app.py'
    app.parent.mkdir()
    app.write_bytes(b'raw\r\nbytes')
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    (runtime / 'deployment-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'build_id': 'bom',
        'files': {'edge_hub/app.py': hashlib.sha256(b'raw\r\nbytes').hexdigest()}}), encoding='utf-8-sig')
    assert verify_files(tmp_path)['disk_matches_manifest']
    assert loaded_identity(tmp_path)['build_id'] == 'bom'


def test_manifest_verification_and_process_identity(tmp_path):
    app = tmp_path / "edge_hub/app.py"
    app.parent.mkdir()
    app.write_text("old", encoding="utf-8")
    manifest = {"schema_version": 1, "build_id": "test-build", "source_commit": "abc",
                "files": {"edge_hub/app.py": hashlib.sha256(app.read_bytes()).hexdigest()}}
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    (runtime / "deployment-manifest.json").write_text(json.dumps(manifest))
    loaded = loaded_identity(tmp_path)
    assert loaded["build_id"] == "test-build"
    assert verify_files(tmp_path)["disk_matches_manifest"]
    app.write_text("new", encoding="utf-8")
    assert loaded["build_id"] == "test-build"  # captured process identity stays unchanged
    assert loaded_identity(tmp_path)["build_id"] is None
    assert verify_files(tmp_path)["changed"] == ["edge_hub/app.py"]


def test_missing_manifest_does_not_claim_version(tmp_path):
    assert loaded_identity(tmp_path)["build_id"] is None
    assert not verify_files(tmp_path)["disk_matches_manifest"]


def test_manifest_rejects_paths_outside_code_tree(tmp_path):
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    for unsafe in ["../outside", "/absolute", "C:/outside", ".runtime/operator-key.txt"]:
        (runtime / "deployment-manifest.json").write_text(json.dumps({
            "schema_version": 1, "build_id": "x", "files": {unsafe: "0" * 64}}))
        report = verify_files(tmp_path)
        assert not report["disk_matches_manifest"]
        assert report["status"] == "invalid_manifest"


@pytest.mark.parametrize("live_build,expected", [("new", True), ("old", False), (None, False)])
def test_checker_distinguishes_stale_process_without_restart(tmp_path, monkeypatch, live_build, expected):
    from tools import verify_deployment as checker

    monkeypatch.setattr(checker, "verify_files", lambda _: {
        "disk_matches_manifest": True, "build_id": "new"})

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, limit):
            return json.dumps({"deployment": {"build_id": live_build}}).encode()

    class Opener:
        def open(self, url, timeout):
            assert url == "http://127.0.0.1:8000/health"
            assert timeout == 4
            return Response()

    def opener(*handlers):
        assert handlers[0].proxies == {}  # never forward to a configured Internet proxy
        assert isinstance(handlers[1], checker.NoRedirect)
        return Opener()

    monkeypatch.setattr(checker, "build_opener", opener)
    report = checker.check(tmp_path)
    assert report["ready"] is expected
    assert report["services_modified"] is False
    assert report["hardware_acceptance"] is False


def test_source_missing_prevents_readiness_and_missing_target_is_reported(tmp_path):
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    (runtime / "deployment-manifest.json").write_text(json.dumps({
        "schema_version": 1, "build_id": "x", "files": {"missing.py": "0" * 64},
        "missing_source_files": ["deleted-at-source.py"]}))
    report = verify_files(tmp_path)
    assert not report["disk_matches_manifest"]
    assert report["missing"] == ["missing.py"]
    assert report["source_missing_count"] == 1


@pytest.mark.parametrize('failure', ['changed', 'missing', 'source_missing'])
def test_startup_identity_requires_entire_inventory_not_only_app(tmp_path, failure):
    app = tmp_path / 'edge_hub/app.py'
    app.parent.mkdir()
    app.write_text('unchanged application', encoding='utf-8')
    dependency = tmp_path / 'edge_hub/events.py'
    dependency.write_text('expected dependency', encoding='utf-8')
    manifest = {'schema_version': 1, 'build_id': 'candidate', 'source_commit': 'revision',
                'files': {str(path.relative_to(tmp_path)).replace('\\', '/'):
                          hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (app, dependency)}}
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    if failure == 'changed':
        dependency.write_text('stale dependency', encoding='utf-8')
    elif failure == 'missing':
        dependency.unlink()
    else:
        manifest['missing_source_files'] = ['missing-at-source.py']
    (runtime / 'deployment-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    loaded = loaded_identity(tmp_path)
    assert loaded['app_sha256'] == hashlib.sha256(app.read_bytes()).hexdigest()
    assert loaded['build_id'] is None
    assert loaded['source_commit'] is None


def test_successful_full_inventory_identity_remains_a_captured_snapshot(tmp_path):
    app = tmp_path / 'edge_hub/app.py'
    app.parent.mkdir()
    app.write_text('app', encoding='utf-8')
    dependency = tmp_path / 'edge_hub/events.py'
    dependency.write_text('events', encoding='utf-8')
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    (runtime / 'deployment-manifest.json').write_text(json.dumps({
        'schema_version': 1, 'build_id': 'captured', 'source_commit': 'revision',
        'files': {'edge_hub/' + path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (app, dependency)}}), encoding='utf-8')
    captured = loaded_identity(tmp_path)
    assert captured['build_id'] == 'captured'
    dependency.write_text('later sync', encoding='utf-8')
    assert captured['build_id'] == 'captured'
    assert loaded_identity(tmp_path)['build_id'] is None
