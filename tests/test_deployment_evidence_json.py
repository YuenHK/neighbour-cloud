import hashlib
import json

import pytest

from edge_hub.deployment import loaded_identity, read_evidence_object, verify_files
from tools import verify_deployment as checker


@pytest.mark.parametrize('target', ['manifest', 'health'])
@pytest.mark.parametrize('extra', [
    b'"build_id":"old",', b'"build_\\u0069d":"old",',
    b'"meta":{"x":1,"x":2},', b'"meta":NaN,', b'"meta":Infinity,',
    b'"meta":-Infinity,', b'"meta":1e999,',
    b'"meta":' + b'[' * 33 + b'0' + b']' * 33 + b',',
])
def test_ambiguous_or_nonfinite_evidence_cannot_claim_identity(tmp_path, monkeypatch, target, extra):
    app = tmp_path / 'edge_hub/app.py'
    app.parent.mkdir()
    app.write_bytes(b'fixture')
    manifest = {'schema_version': 1, 'build_id': 'fixture-build',
                'files': {'edge_hub/app.py': hashlib.sha256(b'fixture').hexdigest()}}
    if target == 'manifest':
        raw = b'{' + extra + json.dumps(manifest).encode()[1:]
        path = tmp_path / '.runtime/deployment-manifest.json'
        path.parent.mkdir()
        path.write_bytes(raw)
        assert verify_files(tmp_path)['status'] == 'invalid_manifest'
        assert loaded_identity(tmp_path)['build_id'] is None
        assert path.read_bytes() == raw
    else:
        raw = b'{"deployment":{' + extra + b'"build_id":"fixture-build"}}'
        monkeypatch.setattr(checker, 'verify_files', lambda _: {
            'disk_matches_manifest': True, 'build_id': 'fixture-build'})

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self, size):
                assert size == 64_001
                return raw

        class Opener:
            def open(self, url, timeout):
                assert url == 'http://127.0.0.1:8000/health' and timeout == 4
                return Response()

        monkeypatch.setattr(checker, 'build_opener', lambda *args: Opener())
        report = checker.check(tmp_path)
        assert report['live_status'] == 'unavailable_or_invalid'
        assert report['ready'] is False and report['live_identity_matches'] is False


@pytest.mark.parametrize('raw', [b'[]', b'null', b'1', b'"text"'])
def test_deployment_evidence_requires_object(raw):
    with pytest.raises(TypeError):
        read_evidence_object(raw, max_bytes=100)


def test_exact_byte_limit_bom_and_braces_inside_strings():
    raw = b'\xef\xbb\xbf' + json.dumps({'text': '[' * 100 + '{' * 100 + '\\"'}).encode()
    assert read_evidence_object(raw, max_bytes=len(raw))['text'].startswith('[' * 100)
    with pytest.raises(ValueError, match='too large'):
        read_evidence_object(raw, max_bytes=len(raw) - 1)
