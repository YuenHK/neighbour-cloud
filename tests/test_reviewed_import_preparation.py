import dataclasses
import hashlib

import httpx
import pytest
from test_cloud_avatar_vrm import model_vrm
from test_reviewed_model_imports import descriptor

from deploy.cloud.reviewed_model_imports import ReviewedImportUnavailable, ReviewedModelImporter
from deploy.cloud.reviewed_vrm_prepare import RECIPE_ID


def release_fixture(handler):
    data = model_vrm()
    row = dataclasses.replace(descriptor(data),
        download_url='https://github.com/original/artist/releases/download/v1.0/model.vrm')
    return row, data, ReviewedModelImporter(reviewed=[row], transport=httpx.MockTransport(handler))


def test_public_release_follows_one_exact_cdn_hop_without_cookies_or_credentials():
    calls = []
    def handler(request):
        assert not request.headers.get('cookie') and not request.headers.get('authorization')
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(302, headers={'location': 'https://release-assets.githubusercontent.com/github-production-release-asset-2e65be/123/file?temporary=public',
                'set-cookie': 'upstream=not-forwarded; Path=/'})
        return httpx.Response(200, content=data)
    row, data, importer = release_fixture(handler)
    assert importer.preview(row.id) == data and len(calls) == 2


@pytest.mark.parametrize('target', ['https://127.0.0.1/private', 'http://release-assets.githubusercontent.com/github-production-release-asset-2e65be/file',
    'https://release-assets.githubusercontent.com.evil.test/github-production-release-asset-2e65be/file',
    'https://user:password@release-assets.githubusercontent.com/github-production-release-asset-2e65be/file',
    'https://release-assets.githubusercontent.com:8080/github-production-release-asset-2e65be/file',
    'https://release-assets.githubusercontent.com/unrelated/file'])
def test_public_release_redirect_cannot_escape_its_cdn_boundary(target):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={'location': target})
    row, _, importer = release_fixture(handler)
    with pytest.raises(ReviewedImportUnavailable):
        importer.preview(row.id)
    assert len(calls) == 1


def test_release_cdn_cannot_chain_another_redirect():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={'location': 'https://release-assets.githubusercontent.com/github-production-release-asset-2e65be/file'})
    row, _, importer = release_fixture(handler)
    with pytest.raises(ReviewedImportUnavailable):
        importer.preview(row.id)
    assert len(calls) == 2


@pytest.mark.parametrize('corrupt', [False, True])
def test_preparation_only_runs_after_original_digest_then_checks_prepared_digest(monkeypatch, corrupt):
    output, original, calls = model_vrm(), b'pinned-public-original'*1024, []
    row = dataclasses.replace(descriptor(output), prepare_recipe=RECIPE_ID,
        download_bytes=len(original), download_sha256=hashlib.sha256(original).hexdigest())
    def prepare(data, **options):
        calls.append(options)
        assert data == original
        assert options == {'recipe': RECIPE_ID, 'expected_output_sha256': row.sha256}
        return output
    monkeypatch.setattr('deploy.cloud.reviewed_vrm_prepare.prepare_vrm', prepare)
    importer = ReviewedModelImporter(reviewed=[row], transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=(b'corrupt' if corrupt else original))))
    if corrupt:
        with pytest.raises(ReviewedImportUnavailable):
            importer.preview(row.id)
        assert calls == []
    else:
        assert importer.preview(row.id) == output and len(calls) == 1
