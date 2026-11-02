import hashlib
import json
import sys

import pytest

from tools import check_robomaster_sdk as sdk


def metadata(checksum):
    return {'info': {'name': 'robomaster', 'version': 'fixture'}, 'urls': [{
        'filename': 'robomaster-1-py3-none-any.whl', 'digests': {'sha256': checksum}}]}


@pytest.mark.parametrize('checksum', [None, '', 'abc', 'A' * 64, '0' * 64])
def test_checksum_gate_is_separate_from_tag_or_verified_bytes(checksum):
    report = sdk.assess(metadata(checksum), 3, 12, 'win_amd64')
    valid = checksum == '0' * 64
    assert report['compatible_binary_available'] is True
    assert report['checksum_recorded_candidate_available'] is valid
    assert report['artifacts'][0]['sha256_recorded'] is valid
    assert report['artifact_bytes_verified'] is False
    assert report['status'] == ('dependency_review_required' if valid else 'artifact_checksum_review_required')


def test_existing_report_rejected_before_read_or_network(tmp_path, monkeypatch):
    output = tmp_path / 'keep.json'
    output.write_bytes(b'previous evidence')
    monkeypatch.setattr(sys, 'argv', ['sdk', '--report', str(output)])
    monkeypatch.setattr(sdk, 'build_opener', lambda *a: pytest.fail('network forbidden'))
    with pytest.raises(FileExistsError):
        sdk.main()
    assert output.read_bytes() == b'previous evidence'


def test_offline_snapshot_bound_and_unverified_provenance(tmp_path, monkeypatch):
    source, output = tmp_path / 'metadata.json', tmp_path / 'new.json'
    raw = json.dumps(metadata('0' * 64)).encode()
    source.write_bytes(raw)
    monkeypatch.setattr(sys, 'argv', ['sdk', '--metadata', str(source), '--report', str(output)])
    monkeypatch.setattr(sdk, 'build_opener', lambda *a: pytest.fail('network forbidden'))
    monkeypatch.setattr(sdk.platform, 'python_implementation', lambda: 'CPython')
    assert sdk.main() == 0
    report = json.loads(output.read_text())
    assert report['metadata_sha256'] == hashlib.sha256(raw).hexdigest()
    assert report['metadata_origin'] == 'local_snapshot_unverified'
    assert report['sdk_installed'] is report['sdk_import_tested'] is False
    assert source.read_bytes() == raw


@pytest.mark.parametrize('raw', [b'{' + b' ' * 2_000_000,
                                    b'{"info":{},"info":{"name":"robomaster"}}'],
                         ids=['oversize', 'duplicate-key'])
def test_invalid_snapshot_cannot_write_report(tmp_path, monkeypatch, raw):
    source, output = tmp_path / 'metadata.json', tmp_path / 'new.json'
    source.write_bytes(raw)
    monkeypatch.setattr(sys, 'argv', ['sdk', '--metadata', str(source), '--report', str(output)])
    with pytest.raises(ValueError):
        sdk.main()
    assert not output.exists()


def test_fixed_endpoint_proxy_redirect_and_read_budget(tmp_path, monkeypatch):
    output = tmp_path / 'new.json'
    raw = json.dumps(metadata(None)).encode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, size):
            assert size == sdk.METADATA_LIMIT + 1
            return raw

    class Opener:
        def open(self, url, timeout):
            assert url == sdk.INDEX_URL and timeout == 20
            return Response()

    def opener(*handlers):
        assert handlers[0].proxies == {} and isinstance(handlers[1], sdk.NoRedirect)
        assert handlers[1].redirect_request(None, None, 302, None, None, 'https://other/') is None
        return Opener()

    monkeypatch.setattr(sdk, 'build_opener', opener)
    monkeypatch.setattr(sys, 'argv', ['sdk', '--report', str(output)])
    assert sdk.main() == 2
    assert json.loads(output.read_text())['metadata_origin'] == 'fixed_pypi_endpoint'
