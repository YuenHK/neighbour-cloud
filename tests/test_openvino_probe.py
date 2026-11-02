import hashlib

import pytest

from tools import probe_openvino_person as probe


def fake_assets(monkeypatch):
    payloads = {'xml': b'<net/>', 'bin': b'weights'}
    monkeypatch.setattr(probe, 'ASSETS', {
        ext: (len(raw), hashlib.sha384(raw).hexdigest()) for ext, raw in payloads.items()})
    return payloads


def test_cache_verifies_all_before_writing(tmp_path, monkeypatch):
    payloads = fake_assets(monkeypatch)

    def fetch(url, **kwargs):
        if url == probe.LICENSE:
            return b'Apache License Version 2.0'
        return payloads[url.rsplit('.', 1)[1]]

    destination = tmp_path / 'candidate'
    result = probe.cache(destination, fetch)
    assert result['formal_evaluation_eligible'] is False
    assert result['scope'] == 'candidate-cache-only'
    assert (destination / (probe.MODEL + '.bin')).read_bytes() == b'weights'
    with pytest.raises(FileExistsError):
        probe.cache(destination, fetch)


@pytest.mark.parametrize('failure', ['hash', 'size', 'license'])
def test_bad_asset_never_creates_cache(tmp_path, monkeypatch, failure):
    payloads = fake_assets(monkeypatch)

    def fetch(url, **kwargs):
        if url == probe.LICENSE:
            return b'wrong license'
        ext = url.rsplit('.', 1)[1]
        if ext == 'bin' and failure != 'license':
            return b'changed' if failure == 'hash' else b'longer weights'
        return payloads[ext]

    destination = tmp_path / 'candidate'
    with pytest.raises(ValueError):
        probe.cache(destination, fetch)
    assert not destination.exists()


def test_xml_declarations_rejected_even_with_matching_hash(monkeypatch):
    raw = b'<!DOCTYPE net><net/>'
    monkeypatch.setattr(probe, 'ASSETS', {'xml': (len(raw), hashlib.sha384(raw).hexdigest())})
    with pytest.raises(ValueError, match='declarations'):
        probe.verify(raw, 'xml')


def test_0202_cache_uses_separate_pinned_profile(tmp_path, monkeypatch):
    payloads = {'xml': b'<net/>', 'bin': b'0202 weights'}
    monkeypatch.setattr(probe, 'ASSETS_0202', {
        ext: (len(raw), hashlib.sha384(raw).hexdigest()) for ext, raw in payloads.items()})
    urls = []
    def fetch(url, **kwargs):
        urls.append(url)
        return (b'Apache License Version 2.0' if url == probe.LICENSE
                else payloads[url.rsplit('.', 1)[1]])
    destination = tmp_path / '0202'
    report = probe.cache(destination, fetch, probe.MODEL_0202)
    assert probe.model_profile(probe.MODEL_0202)[1:] == ([1, 3, 512, 512], 0)
    assert all('/person-detection-0202/FP32/' in url for url in urls[:2])
    assert (destination / 'person-detection-0202.bin').read_bytes() == payloads['bin']
    assert report['formal_evaluation_eligible'] is False
    with pytest.raises(ValueError, match='profile'):
        probe.cache(tmp_path / 'unknown', fetch, 'unreviewed')
    assert not (tmp_path / 'unknown').exists()
