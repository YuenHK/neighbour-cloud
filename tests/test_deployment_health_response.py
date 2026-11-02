import json

import pytest

from tools import verify_deployment as checker


def check_response(tmp_path, monkeypatch, raw):
    sizes, closed = [], []
    monkeypatch.setattr(checker, 'verify_files', lambda _: {
        'disk_matches_manifest': True, 'build_id': 'fixture-build'})
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            closed.append(True)
        def read(self, size):
            sizes.append(size)
            return raw[:size]
    class Opener:
        def open(self, url, timeout):
            assert url == 'http://127.0.0.1:8000/health' and timeout == 4
            return Response()
    def opener(*handlers):
        assert handlers[0].proxies == {} and isinstance(handlers[1], checker.NoRedirect)
        return Opener()
    monkeypatch.setattr(checker, 'build_opener', opener)
    report = checker.check(tmp_path)
    assert sizes == [64_001] and closed == [True]
    assert report['services_modified'] is False and report['hardware_acceptance'] is False
    assert 'private-' not in json.dumps(report)
    return report


def identity():
    return json.dumps({'deployment': {'build_id': 'fixture-build'}}).encode('utf-8')


def test_oversized_valid_json_prefix_cannot_claim_live_version(tmp_path, monkeypatch):
    prefix = identity()
    raw = prefix + b' ' * (64_000 - len(prefix)) + b'private-unread-tail'
    report = check_response(tmp_path, monkeypatch, raw)
    assert report['live_status'] == 'unavailable_or_invalid'
    assert report['live_identity_matches'] is False and report['ready'] is False


@pytest.mark.parametrize('bom', [False, True])
def test_exact_response_boundary_and_utf8_bom_remain_valid(tmp_path, monkeypatch, bom):
    prefix = (b'\xef\xbb\xbf' if bom else b'') + identity()
    raw = prefix + b' ' * (64_000 - len(prefix))
    report = check_response(tmp_path, monkeypatch, raw)
    assert report['live_identity_matches'] is True and report['ready'] is True


@pytest.mark.parametrize('raw', [
    b'[' * 20_000 + b'0' + b']' * 20_000,
    identity().decode('utf-8').encode('utf-16'),
    b'{"private-data":"\xff"}',
    b'{"private-data":}',
], ids=['deep-json', 'utf16', 'invalid-utf8', 'bad-syntax'])
def test_invalid_health_encoding_syntax_or_depth_fails_closed(tmp_path, monkeypatch, raw):
    report = check_response(tmp_path, monkeypatch, raw)
    assert report['live_status'] == 'unavailable_or_invalid'
    assert report['live_identity_matches'] is False and report['ready'] is False
