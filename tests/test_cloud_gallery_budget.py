import hashlib
import json

import pytest

from deploy.cloud import web_assets


def bundle(tmp_path, zip_name, amount):
    files = {'resident.html': b'<html></html>', 'assets/program.js': b'x'*40,
             zip_name: b'p'*amount}
    for name, data in files.items():
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    rows = [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for name, data in files.items()]
    (tmp_path/'CLOUD-ASSETS.json').write_text(json.dumps({'format': 'neighbour-cloud-assets-v1', 'files': rows}))


def limits(monkeypatch):
    monkeypatch.setattr(web_assets, 'MAX_PROGRAM_BYTES', 100)
    monkeypatch.setattr(web_assets, 'MAX_REVIEWED_GALLERY_BYTES', 100)
    monkeypatch.setattr(web_assets, 'reviewed_gallery_paths', lambda: {'assets/gallery/reviewed.zip'})


def test_approved_optional_gallery_does_not_expand_or_use_program_budget(tmp_path, monkeypatch):
    limits(monkeypatch)
    bundle(tmp_path, 'assets/gallery/reviewed.zip', 90)
    assets = web_assets.CloudWebAssets(tmp_path)
    assert '/assets/gallery/reviewed.zip' in assets.files


def test_optional_gallery_has_its_own_finite_budget(tmp_path, monkeypatch):
    limits(monkeypatch)
    bundle(tmp_path, 'assets/gallery/reviewed.zip', 101)
    with pytest.raises(ValueError, match='too_large'):
        web_assets.CloudWebAssets(tmp_path)


def test_unreviewed_file_cannot_borrow_gallery_capacity(tmp_path, monkeypatch):
    limits(monkeypatch)
    bundle(tmp_path, 'assets/gallery/unreviewed.zip', 90)
    with pytest.raises(ValueError, match='too_large'):
        web_assets.CloudWebAssets(tmp_path)


def test_gallery_allowance_only_contains_pinned_gallery_archives_and_thumbnails():
    paths = web_assets.reviewed_gallery_paths()
    assert 'assets/gallery/denpaborisu-cat1.zip' in paths
    assert all(name.startswith('assets/gallery/') and name.endswith(('.zip', '.webp')) for name in paths)
    assert not any('raw.githubusercontent.com' in name for name in paths)
