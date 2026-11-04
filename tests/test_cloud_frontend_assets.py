import json

import pytest

from tools.cloud_frontend_assets import cloud_styles, package


@pytest.fixture
def build(tmp_path):
    source = tmp_path / 'isolated'
    source.mkdir()
    names = ['assets/resident-abcdefgh.js', 'assets/index-abcdefgh.css',
             'assets/js/sdk/Core/live2dcubismcore.min.js', 'assets/hiyori_free_zh-abcdefgh.zip',
             'assets/ort-wasm-test.wasm', 'assets/duckdb.wasm', 'assets/test.map',
             'assets/hiyori_pro_zh-test.zip', 'assets/unused.vrm', 'airi-local-profile.json',
             'sw.js', 'registerSW.js', 'assets/large.ttf', 'assets/gallery/mark.zip',
             'assets/gallery/arbitrary.zip', 'assets/elsewhere/mark.zip']
    for name in names:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    (source / 'index.html').write_text('''<script async src="https://analytics.example/"></script>
    <script src="/assets/js/sdk/Core/live2dcubismcore.min.js"></script>
    <script type="module" crossorigin src="/assets/resident-abcdefgh.js"></script>
    <link rel="stylesheet" crossorigin href="/assets/index-abcdefgh.css">''', encoding='utf-8')
    proof = tmp_path / 'verification.json'
    proof.write_text(json.dumps({'codes': {'lint': 0, 'typecheck': 0, 'build': 0}, 'restore_errors': [],
        'native_source_restored': True, 'live_dist_written': False}), encoding='utf-8')
    return source, tmp_path / 'output', proof


def test_cloud_package_has_a_handshake_only_entry_and_omits_native_data_and_dead_assets(build):
    source, output, proof = build
    result = package(source, output, proof)
    manifest = json.loads((output / 'CLOUD-ASSETS.json').read_text(encoding='utf-8'))
    files = {row['path'] for row in manifest['files']}
    assert files == {'resident.html', 'assets/resident-abcdefgh.js', 'assets/index-abcdefgh.css',
        'assets/js/sdk/Core/live2dcubismcore.min.js', 'assets/hiyori_free_zh-abcdefgh.zip', 'assets/ort-wasm-test.wasm',
        'assets/hiyori_pro_zh-test.zip', 'assets/unused.vrm', 'assets/gallery/mark.zip'}
    assert result['files'] == len(files) and result['deployed'] is False
    html = (output / 'resident.html').read_text(encoding='utf-8')
    assert 'analytics.example' not in html and 'registerSW' not in html
    assert 'name="neighbour-cloud-entry"' in html and '/cloud/frame-entry.js' in html
    assert 'type="module" crossorigin src="/assets/resident-' not in html
    assert (source / 'airi-local-profile.json').is_file()
    with pytest.raises(ValueError):
        package(source, output, proof)


def test_failed_build_or_missing_required_runtime_is_not_packaged(build):
    source, output, proof = build
    bad = json.loads(proof.read_text(encoding='utf-8'))
    bad['codes']['typecheck'] = 1
    proof.write_text(json.dumps(bad), encoding='utf-8')
    with pytest.raises(ValueError):
        package(source, output, proof)
    assert not output.exists()
    bad['codes']['typecheck'] = 0
    proof.write_text(json.dumps(bad), encoding='utf-8')
    (source / 'assets/ort-wasm-test.wasm').unlink()
    with pytest.raises(ValueError):
        package(source, output, proof)
    assert not output.exists()


def test_unused_cdn_fonts_are_removed_without_changing_the_layout_or_system_font():
    css = b'@font-face{font-family:test;src:url(https://cdn.jsdelivr.net/fontsource/fonts/test.woff2)}.card{color:green}@font-face{font-family:local;src:url(/assets/local.woff2)}'
    assert cloud_styles(css) == b'.card{color:green}@font-face{font-family:local;src:url(/assets/local.woff2)}'


def test_self_hosted_lipsync_runtime_is_packaged_without_broadening_wasm_selection(build):
    source, output, proof = build
    (source / 'assets/wlipsync-reviewed.wasm').write_bytes(b'installed audio analysis runtime')
    (source / 'assets/audio-processor-reviewed.js').write_text('registerProcessor("wlipsync-processor", Processor)')
    package(source, output, proof)
    assert (output / 'assets/wlipsync-reviewed.wasm').is_file()
    assert (output / 'assets/audio-processor-reviewed.js').is_file()
    assert not (output / 'assets/duckdb.wasm').exists()
