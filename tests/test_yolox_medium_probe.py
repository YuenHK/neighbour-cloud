from types import SimpleNamespace

import pytest

from tools import probe_yolox_medium as probe


def test_cache_records_local_hash_without_claiming_official_digest_or_weight_clearance(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'MODEL_SIZE', 4)
    def fetch(url, **kwargs):
        return b'Apache License Version 2.0' if url == probe.LICENSE_URL else b'onnx'
    report = probe.cache(tmp_path / 'candidate', fetch)
    assert report['bytes'] == 4 and len(report['sha256']) == 64
    assert report['upstream_digest_available'] is False
    assert report['weight_license_cleared_for_deployment'] is False
    with pytest.raises(FileExistsError):
        probe.cache(tmp_path / 'candidate', lambda *a, **kw: pytest.fail('must not fetch again'))


@pytest.mark.parametrize('bad_license', [False, True])
def test_invalid_asset_or_license_leaves_no_candidate_directory(tmp_path, monkeypatch, bad_license):
    monkeypatch.setattr(probe, 'MODEL_SIZE', 4)
    def fetch(url, **kwargs):
        if url == probe.LICENSE_URL:
            return b'changed' if bad_license else b'Apache License Version 2.0'
        return b'bad'
    with pytest.raises(ValueError):
        probe.cache(tmp_path / 'candidate', fetch)
    assert not (tmp_path / 'candidate').exists()


def test_smoke_rejects_hash_before_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'MODEL_SIZE', 4)
    (tmp_path / 'yolox_m.onnx').write_bytes(b'onnx')
    with pytest.raises(ValueError, match='hash'):
        probe.smoke(tmp_path, '0' * 64)


def test_tensor_contract_only_accepts_reviewed_shape():
    session = SimpleNamespace(
        get_inputs=lambda: [SimpleNamespace(type='tensor(float)', shape=[1, 3, 640, 640])],
        get_outputs=lambda: [SimpleNamespace(type='tensor(float)', shape=[1, 8400, 85])])
    probe.validate_session(session)
    session.get_outputs = lambda: [SimpleNamespace(type='tensor(float)', shape=[1, 8400, 6])]
    with pytest.raises(ValueError, match='tensor contract'):
        probe.validate_session(session)


def test_untrusted_redirect_host_is_rejected_before_request():
    with pytest.raises(ValueError, match='redirect'):
        probe.bounded_fetch(None, 'https://unreviewed.example/model', limit=4)


def test_redirect_cannot_reach_unreviewed_host():
    import httpx

    requested = []
    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={'location': 'https://unreviewed.example/model'})
    with (httpx.Client(transport=httpx.MockTransport(respond)) as client,
          pytest.raises(ValueError, match='redirect')):
        probe.bounded_fetch(client, probe.MODEL_URL, limit=4)
    assert requested == [probe.MODEL_URL]


def test_stream_size_limit_rejects_oversized_response():
    import httpx

    with (httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'12345'))) as client,
          pytest.raises(ValueError, match='budget')):
        probe.bounded_fetch(client, probe.MODEL_URL, limit=4)


@pytest.mark.parametrize('failure', ['status', 'timeout'])
def test_download_failure_traceback_redacts_signed_url_and_does_not_retry(failure):
    import traceback

    import httpx

    requests = []
    signed = 'https://release-assets.githubusercontent.com/model?secret=PRIVATE_SIGNATURE'
    def respond(request):
        requests.append(str(request.url))
        if len(requests) == 1:
            return httpx.Response(302, headers={'location': signed})
        if failure == 'timeout':
            raise httpx.ReadTimeout('private failure ' + signed, request=request)
        return httpx.Response(403, text='private response ' + signed)
    with (httpx.Client(transport=httpx.MockTransport(respond)) as client,
          pytest.raises(RuntimeError, match='no automatic retry') as error):
        probe.bounded_fetch(client, probe.MODEL_URL, limit=4)
    rendered = ''.join(traceback.format_exception(error.value))
    assert 'PRIVATE_SIGNATURE' not in rendered
    assert 'release-assets.githubusercontent.com' not in rendered
    assert requests == [probe.MODEL_URL, signed]


def test_malformed_redirect_port_has_fixed_error_without_private_context():
    import traceback

    malformed = 'https://github.com:PRIVATE_SIGNATURE/model'
    with pytest.raises(ValueError, match='unreviewed') as error:
        probe.bounded_fetch(None, malformed, limit=4)
    assert 'PRIVATE_SIGNATURE' not in ''.join(traceback.format_exception(error.value))


def test_missing_redirect_location_is_fixed_error():
    import httpx

    with (httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(302))) as client,
          pytest.raises(ValueError, match='missing model download redirect')):
        probe.bounded_fetch(client, probe.MODEL_URL, limit=4)
