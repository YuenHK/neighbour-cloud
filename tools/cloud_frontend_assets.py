"""Package an isolated, verified AIRI build, never the native live dist.

Select program assets for a fixed Hiyori Free resident view, omit debugging,
offline precache, native profiles, fonts, unused AI DB/vision/VRM models.
No upload, deployment, service restart, credentials or data are performed.
"""
import hashlib
import json
import re
import shutil
from pathlib import Path

from deploy.cloud.web_assets import SUFFIX_TYPES, CloudWebAssets


def cloud_styles(data):
    """Drop unused CDN font declarations, keep the desk's existing system font.

    Retain all selectors/layout/colour rules and any same-origin font faces.
    """
    text = data.decode('utf-8')

    def face(match):
        block = match[0]
        return '' if 'https://cdn.jsdelivr.net/fontsource/' in block else block

    return re.sub(r'@font-face\s*\{[^{}]*\}', face, text).encode('utf-8')


def package(source, output, verification):
    source, output = Path(source).resolve(strict=True), Path(output).absolute()
    proof = json.loads(Path(verification).read_text(encoding='utf-8'))
    if (proof.get('codes') != {'lint': 0, 'typecheck': 0, 'build': 0}
            or proof.get('restore_errors') or proof.get('native_source_restored') is not True
            or proof.get('live_dist_written') is not False or output.exists()
            or source.is_relative_to(output) or output.is_relative_to(source)):
        raise ValueError('isolated_verified_build_required')
    html = (source / 'index.html').read_text(encoding='utf-8')
    entry = re.findall(r'<script type="module" crossorigin src="(/assets/[\w-]+\.js)"></script>', html)
    css = re.findall(r'<link rel="stylesheet" crossorigin href="(/assets/[\w-]+\.css)">', html)
    sdk = re.findall(r'<script src="(/assets/js/[\w./-]+/live2dcubismcore\.min\.js)"></script>', html)
    if len(entry) != 1 or len(sdk) != 1 or not css:
        raise ValueError('cloud_build_entry_requires_review')
    selected = []
    catalogue = json.loads((Path(__file__).resolve().parents[1] / 'airi_overlay/cloud-model-gallery.json').read_text(encoding='utf-8'))
    gallery_paths = {item['archive'].lstrip('/') for item in catalogue['models']}
    for path in source.rglob('*'):
        if not path.is_file():
            continue
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError('cloud_assets_symlink')
        relative = path.relative_to(source)
        if relative.as_posix() in ('estate-theme.css', 'estate-mark.svg'):
            selected.append(path)
        elif relative.parts[0] == 'assets' and path.suffix in SUFFIX_TYPES:
            if path.suffix == '.wasm' and not path.name.startswith(('ort-wasm-', 'wlipsync-')):
                continue
            gallery = relative.as_posix() in gallery_paths
            if path.suffix == '.zip' and not gallery and not path.name.startswith(('hiyori_free_zh-', 'hiyori_pro_zh-')):
                continue
            selected.append(path)
    paths = {path.relative_to(source).as_posix() for path in selected}
    if (any(name.lstrip('/') not in paths for name in entry + css + sdk)
            or not any(name.startswith('assets/hiyori_free_zh-') for name in paths)
            or not any(name.startswith('assets/ort-wasm-') and name.endswith('.wasm') for name in paths)):
        raise ValueError('cloud_resident_assets_incomplete')
    # Fresh document: no analytics, service worker, OpenGraph trackers, inline
    # providers or module execution before the parent identity handshake.
    resident = ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<title>鄰伴 · 居民服務台</title><meta name="theme-color" content="#f3f7f4" id="themeColor">'
        '<meta name="neighbour-cloud-entry" content="' + entry[0] + '">'
        + ''.join('<link rel="stylesheet" href="' + name + '">' for name in css)
        + '</head><body><div id="app"></div><script src="' + sdk[0] + '"></script>'
        '<script type="module" src="/cloud/frame-entry.js"></script></body></html>')
    output.mkdir(parents=True)
    for path in selected:
        target = output / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == '.css':
            target.write_bytes(cloud_styles(path.read_bytes()))
        else:
            shutil.copyfile(path, target)
    (output / 'resident.html').write_text(resident, encoding='utf-8')
    files = []
    for path in sorted(output.rglob('*')):
        if path.is_file():
            with path.open('rb') as reader:
                digest = hashlib.file_digest(reader, 'sha256').hexdigest()
            files.append({'path': path.relative_to(output).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest})
    manifest = {'format': 'neighbour-cloud-assets-v1', 'files': files}
    (output / 'CLOUD-ASSETS.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    CloudWebAssets(output)  # Same loader that the host uses; verify all bytes.
    return {'files': len(files), 'bytes': sum(row['bytes'] for row in files), 'deployed': False}
