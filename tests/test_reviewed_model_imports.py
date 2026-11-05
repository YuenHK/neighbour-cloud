import dataclasses
import hashlib
import io
import stat
import zipfile

import httpx
import pytest
from test_cloud_avatar_vrm import model_vrm

from deploy.cloud.reviewed_model_imports import (
    STATIC_MODEL_CREDITS,
    ReviewedImportUnavailable,
    ReviewedModel,
    ReviewedModelImporter,
    reviewed_models,
)


def descriptor(content, *, member=None, package=None):
    package = content if package is None else package
    return ReviewedModel(
        id='public-fixture', name='Public fixture', source='synthetic',
        source_name='Synthetic author', source_url='https://author.invalid/model',
        license_url='https://author.invalid/license', credit='Public fixture author',
        notice='Synthetic application inclusion permission', bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        download_url='https://author.invalid/fixed/model.zip' if member else 'https://author.invalid/fixed/model.vrm',
        download_bytes=len(package), download_sha256=hashlib.sha256(package).hexdigest(),
        member=member, application_only=True,
    )


def zipped(content, name='nested/model.vrm', *, duplicate=False, symlink=False):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(name)
        if symlink:
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, content)
        if duplicate:
            archive.writestr(name, content)
        archive.writestr('unused/instructions.exe', b'not executed or extracted')
    return buffer.getvalue()


def client(row, body, status=200, headers=None):
    calls = []

    def endpoint(request):
        calls.append(request)
        assert str(request.url) == row.download_url
        assert request.headers['Accept-Encoding'] == 'identity'
        assert 'authorization' not in request.headers
        assert 'cookie' not in request.headers
        return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers or {})

    return ReviewedModelImporter(reviewed=[row], transport=httpx.MockTransport(endpoint)), calls


def test_only_reviewed_identifiers_are_accepted_without_network():
    row = descriptor(model_vrm())
    importer, calls = client(row, b'')
    for unknown in ('https://127.0.0.1/private', '../private', 'unreviewed', None, {}):
        with pytest.raises(ReviewedImportUnavailable, match='model_not_reviewed'):
            importer.preview(unknown)
    assert calls == []


def test_direct_verified_content_and_public_catalogue_preserve_notice():
    raw = model_vrm()
    row = descriptor(raw)
    importer, calls = client(row, raw)
    assert importer.preview(row.id) == raw
    public = importer.catalogue()[0]
    assert public['application_only'] and public['credit'] == row.credit
    assert public['notice'] == row.notice and public['format'] == 'vrm'
    assert 'download_url' not in public and 'member' not in public
    assert len(calls) == 1


@pytest.mark.parametrize('status', [301, 302, 401, 403, 429, 500, 503])
def test_error_or_redirect_is_not_followed_retried_or_echoed(status):
    row = descriptor(model_vrm())
    importer, calls = client(row, b'PRIVATE_UPSTREAM_DETAIL', status,
                             {'Location': 'https://127.0.0.1/private'})
    with pytest.raises(ReviewedImportUnavailable) as error:
        importer.preview(row.id)
    assert str(error.value) == 'model_download_unavailable' and len(calls) == 1


@pytest.mark.parametrize('change', ['truncated', 'oversized', 'mutated', 'header', 'encoded'])
def test_immutable_expected_size_hash_and_encoding_are_mandatory(change):
    raw = model_vrm()
    row = descriptor(raw)
    changed = {'truncated': raw[:-1], 'oversized': raw + b'x',
               'mutated': b'x' + raw[1:]}.get(change, raw)
    headers = {'content-length': str(len(raw) + 1)} if change == 'header' else (
        {'content-encoding': 'gzip'} if change == 'encoded' else {})
    importer, calls = client(row, changed, headers=headers)
    with pytest.raises(ReviewedImportUnavailable, match='model_changed_requires_review'):
        importer.preview(row.id)
    assert len(calls) == 1


def test_zip_selects_exact_pinned_entry_without_extracting_unrelated_files(tmp_path, monkeypatch):
    raw = model_vrm()
    package = zipped(raw)
    row = descriptor(raw, member='nested/model.vrm', package=package)
    importer, calls = client(row, package)
    monkeypatch.chdir(tmp_path)
    assert importer.preview(row.id) == raw
    assert list(tmp_path.iterdir()) == [] and len(calls) == 1


@pytest.mark.parametrize('name,options', [('../model.vrm', {}), ('/model.vrm', {}),
    ('C:/model.vrm', {}), ('nested\\model.vrm', {}),
    ('nested/model.vrm', {'duplicate': True}), ('nested/model.vrm', {'symlink': True})])
def test_zip_rejects_traversal_duplicate_and_symlink_entries(name, options):
    raw = model_vrm()
    package = zipped(raw, name, **options)
    row = descriptor(raw, member=name, package=package)
    importer, _ = client(row, package)
    with pytest.raises(ReviewedImportUnavailable, match='model_archive_invalid'):
        importer.preview(row.id)


def test_model_structure_is_checked_after_matching_whole_download_hash():
    raw = b'not a VRM model'.ljust(128, b'x')
    importer, _ = client(descriptor(raw), raw)
    with pytest.raises(ReviewedImportUnavailable, match='model_validation_failed'):
        importer.preview('public-fixture')


def test_concurrent_import_is_rejected_without_another_network_call_and_gate_recovers():
    raw = model_vrm()
    row = descriptor(raw)
    calls = []
    importer = None

    def endpoint(request):
        calls.append(request)
        with pytest.raises(ReviewedImportUnavailable, match='model_import_busy'):
            importer.preview(row.id)
        return httpx.Response(200, content=raw)

    importer = ReviewedModelImporter(reviewed=[row], transport=httpx.MockTransport(endpoint))
    assert importer.preview(row.id) == raw and importer.preview(row.id) == raw
    assert len(calls) == 2


def test_time_budget_is_bounded_and_gate_released():
    raw = model_vrm()
    importer, calls = client(descriptor(raw), raw)
    importer._deadline_seconds = -1
    with pytest.raises(ReviewedImportUnavailable, match='model_download_timeout'):
        importer.preview('public-fixture')
    importer._deadline_seconds = 30
    assert importer.preview('public-fixture') == raw and len(calls) == 2


def test_production_manifest_is_fixed_nonduplicated_and_carries_original_permissions():
    rows = reviewed_models()
    assert len(rows) == 9 and len({row.sha256 for row in rows}) == 9
    assert len({row.source for row in rows}) == 7
    assert all(row.credit and row.license_url and row.notice for row in rows)
    assert all(row.application_only for row in rows if row.source in ('tsukuyomi', 'aituber-onair'))
    with pytest.raises(dataclasses.FrozenInstanceError):
        rows[0].download_url = 'https://127.0.0.1/private'


def test_published_static_cat_and_godette_resolve_exact_original_credit_on_another_device():
    importer = ReviewedModelImporter()
    cat_id = 'cloud-live2d-bc35f1bdbf503abace04cadb524eddbdee5945f717ba265b71505aabde71792f'
    cat = importer.credit(cat_id)
    assert cat == STATIC_MODEL_CREDITS[cat_id]
    assert 'Boris González' in cat['author'] and '公有領域' in cat['notice']
    cat['notice'] = 'caller mutation'
    assert '公有領域' in importer.credit(cat_id)['notice']
    godette = next(row for row in reviewed_models() if row.id == 'godette-original-vrm')
    credit = importer.credit('cloud-vrm-' + godette.sha256)
    assert 'SirRichard94' in credit['author'] and 'Lyuma' in credit['author']
    assert 'CC BY 3.0' in credit['author']
    for invalid in (None, {}, cat_id + '?changed=1', cat_id.replace('live2d', 'vrm'),
                    'cloud-live2d-' + 'a' * 64):
        assert importer.credit(invalid) is None
