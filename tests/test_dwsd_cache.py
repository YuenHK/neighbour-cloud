import hashlib
import io
import zipfile

import httpx
import pytest

from tools.cache_dwsd import CDN, cache, checked_redirect, inspect_archive


def payload():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('DWSD/images/img1.png', b'not decoded')
    return stream.getvalue()


def test_pinned_archive_is_verified_but_never_extracted_or_approved(tmp_path):
    data = payload()
    def handler(request):
        if request.url.host == 'data.mendeley.com':
            return httpx.Response(302, headers={'location': f'https://{CDN}/archive'})
        return httpx.Response(200, content=data)
    path = tmp_path / 'archive.zip'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = cache(client, path, len(data), hashlib.sha256(data).hexdigest())
    assert not report['training_approved'] and not report['formal_evaluation_eligible']
    assert report['archive']['members'] == 1
    assert not (tmp_path / 'DWSD').exists()


def test_archive_hash_failure_and_existing_output_never_overwrite(tmp_path):
    data = payload()
    def handler(request):
        return (httpx.Response(302, headers={'location': f'https://{CDN}/archive'})
                if request.url.host == 'data.mendeley.com' else httpx.Response(200, content=data))
    path = tmp_path / 'archive.zip'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match='hash mismatch'):
            cache(client, path, len(data), '0' * 64)
        with pytest.raises(FileExistsError):
            cache(client, path)
    assert path.read_bytes() == data


def test_untrusted_redirect_and_unsafe_archive_members_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        checked_redirect('https://private.example/archive')
    path = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('../escape.png', b'never extracted')
    with pytest.raises(ValueError, match='unsafe'):
        inspect_archive(path)
