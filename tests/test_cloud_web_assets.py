import hashlib
import json
from pathlib import Path

import pytest

from deploy.cloud.web_assets import CloudWebAssets


def bundle(tmp_path, **changes):
    data = b'<html><meta name="neighbour-cloud-entry" content="/assets/resident-123.js"></html>'
    (tmp_path / 'resident.html').write_bytes(data)
    asset = tmp_path / 'assets/resident-123.js'
    asset.parent.mkdir(exist_ok=True)
    asset.write_bytes(b'export const resident=true')
    manifest = {'format': 'neighbour-cloud-assets-v1', 'files': [
        {'path': str(path.relative_to(tmp_path)).replace('\\', '/'), 'bytes': path.stat().st_size,
         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in (tmp_path / 'resident.html', asset)]}
    manifest.update(changes)
    (tmp_path / 'CLOUD-ASSETS.json').write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


def response(assets, path, stage=False):
    return assets.response(path, storage_acceptance=stage, client_id='public-client-id')


def test_login_shell_is_public_but_has_no_token_profile_or_media_by_default():
    assets = CloudWebAssets()
    shell = response(assets, '/')
    assert shell.status_code == 200 and b'/cloud/shell.js' in shell.body
    assert shell.headers['permissions-policy'] == 'microphone=(), camera=(), autoplay=()'
    config = json.loads(response(assets, '/login-config').body)
    assert config == {'client_id': 'public-client-id'}
    for private in ('/airi-local-profile.json', '/.env', '/settings', '/assets/../data.sqlite3', '/unknown.js'):
        assert response(assets, private) is None
    assert response(assets, '/cloud/resident').status_code == 503
    assert response(assets, '/cloud/resident', True).status_code == 423


def test_reviewed_assets_allow_same_origin_resident_media_only_after_stage(tmp_path):
    bundle(tmp_path)
    assets = CloudWebAssets(tmp_path)
    assert response(assets, '/cloud/resident', True).status_code == 423
    assert response(assets, '/assets/resident-123.js', True) is None
    shell = response(assets, '/')
    assert shell.headers['permissions-policy'] == 'microphone=(self), camera=(), autoplay=(self)'
    resident = response(assets, '/cloud/resident')
    assert resident.status_code == 200 and b'/assets/resident-123.js' in resident.body
    assert "frame-ancestors 'self'" in resident.headers['content-security-policy']
    script = response(assets, '/assets/resident-123.js')
    assert Path(script.path).read_bytes() == b'export const resident=true'
    assert script.headers['content-type'].startswith('text/javascript')


@pytest.mark.parametrize('bad', ['../secret.js', '/secret.js', 'assets//secret.js', 'airi-local-profile.json', 'resident.html'])
def test_manifest_cannot_duplicate_or_select_parent_private_profile(tmp_path, bad):
    manifest = bundle(tmp_path)
    manifest['files'].append({**manifest['files'][0], 'path': bad})
    (tmp_path / 'CLOUD-ASSETS.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        CloudWebAssets(tmp_path)


def test_missing_or_changed_assets_stop_loading_and_no_directory_is_served(tmp_path):
    bundle(tmp_path)
    (tmp_path / 'assets/resident-123.js').write_bytes(b'CHANGED-PRIVATE')
    with pytest.raises(ValueError, match='digest'):
        CloudWebAssets(tmp_path)
    assert response(CloudWebAssets(), '/assets/') is None


def test_cloud_copies_have_no_native_background_or_provider_bootstrap():
    root = Path(__file__).resolve().parents[1]
    app = (root / 'airi_overlay/cloud-app.vue').read_text(encoding='utf-8')
    for native in ('usePWAStore', 'triggerPreload', 'contextBridgeStore', 'serverChannelStore', 'analyticsStore'):
        assert native not in app
    bootstrap = (root / 'airi_overlay/cloud-profile-bootstrap.ts').read_text(encoding='utf-8')
    assert '__NEIGHBOUR_CLOUD_TRANSPORT__' in bootstrap
    for native in ('await fetch(', '127.0.0.1', 'settings/credentials', 'apiKey', 'api_key'):
        assert native not in bootstrap
    assert "transport.fetch('/api/v1/resident/presentation'" in bootstrap
    assert "wasm.wasmPaths = '/assets/onnx-3.8.1/'" in bootstrap
