"""Fixed cloud UI assets; never serves native profiles, data or arbitrary paths.

The resident build is opt-in via a reviewed SHA manifest. The login shell can
be served without it, including in storage acceptance mode; media cannot.
"""
import hashlib
import json
import re
from pathlib import Path

from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from deploy.cloud.admin_assets import CloudAdminAssets
from deploy.cloud.database_profile import unique_object
from deploy.cloud.robot_assets import robot_assets

WEB = Path(__file__).with_name('web')
OVERLAY = Path(__file__).resolve().parents[2] / 'airi_overlay'
SHELL = {
    '/staff-sw.js': (WEB / 'staff-sw.js', 'text/javascript'),
    '/staff.webmanifest': (WEB / 'staff.webmanifest', 'application/manifest+json'),
    '/': (WEB / 'index.html', 'text/html'),
    '/cloud/shell.js': (WEB / 'shell.js', 'text/javascript'),
    '/cloud/shell.css': (WEB / 'shell.css', 'text/css'),
    '/cloud/launch-screen.js': (WEB / 'launch-screen.js', 'text/javascript'),
    '/cloud/launch-screen.css': (WEB / 'launch-screen.css', 'text/css'),
    '/cloud/module-warmup.js': (WEB / 'module-warmup.js', 'text/javascript'),
    # A browser can request these after the real app becomes ready midway
    # through loading the independent cold-start document.
    '/cloud/boot-wait.js': (WEB / 'boot-wait.js', 'text/javascript'),
    '/cloud/boot-wait.css': (WEB / 'boot-wait.css', 'text/css'),
    '/cloud/frame-entry.js': (WEB / 'frame-entry.js', 'text/javascript'),
    '/cloud/admin-entry.js': (WEB / 'admin-entry.js', 'text/javascript'),
    '/cloud/robot-entry.js': (WEB / 'robot-entry.js', 'text/javascript'),
    '/cloud/admin-request.js': (WEB / 'admin-request.js', 'text/javascript'),
    '/cloud/cloud-session.js': (OVERLAY / 'cloud-session.js', 'text/javascript'),
    '/cloud/cloud-frame.js': (OVERLAY / 'cloud-frame.js', 'text/javascript'),
    '/cloud/cloud-transport.js': (OVERLAY / 'cloud-transport.js', 'text/javascript'),
    '/cloud/resident-recovery.js': (OVERLAY / 'resident-recovery.js', 'text/javascript'),
    '/cloud/resident-panel.css': (OVERLAY / 'resident-panel.css', 'text/css'),
    '/cloud/mascot.css': (WEB / 'mascot.css', 'text/css'),
    '/assets/brand/neighbour-house-apricot-v1.webp': (WEB / 'brand/neighbour-house-apricot-v1.webp', 'image/webp'),
    '/assets/brand/favicon-32.png': (WEB / 'brand/favicon-32.png', 'image/png'),
    '/assets/brand/apple-touch-icon-180.png': (WEB / 'brand/apple-touch-icon-180.png', 'image/png'),
    '/assets/brand/icon-192.png': (WEB / 'brand/icon-192.png', 'image/png'),
    '/assets/brand/icon-512.png': (WEB / 'brand/icon-512.png', 'image/png'),
}
SUFFIX_TYPES = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
    '.png': 'image/png', '.avif': 'image/avif', '.webp': 'image/webp', '.ico': 'image/x-icon',
    '.wasm': 'application/wasm', '.zip': 'application/zip', '.onnx': 'application/octet-stream',
    '.json': 'application/json', '.hdr': 'application/octet-stream', '.vrma': 'application/octet-stream', '.vrm': 'application/octet-stream',
    '.woff': 'font/woff', '.woff2': 'font/woff2'}


class CloudWebAssets:
    def __init__(self, resident_root=None, *, governance=False, public_resident=False):
        if type(public_resident) is not bool:
            raise ValueError('explicit_public_resident_mode_required')
        self.public_resident = public_resident
        self.files = {}
        self.resident = None
        self.admin = CloudAdminAssets(governance=governance)
        self.admin.responses.update(robot_assets())
        if resident_root is None:
            return
        root = Path(resident_root)
        manifest = json.loads((root / 'CLOUD-ASSETS.json').read_text(encoding='utf-8'),
                              object_pairs_hook=unique_object)
        if (set(manifest) != {'format', 'files'} or manifest['format'] != 'neighbour-cloud-assets-v1'
                or not isinstance(manifest['files'], list) or not 1 <= len(manifest['files']) <= 2000
                or root.is_symlink() or any(p.is_symlink() for p in root.parents)):
            raise ValueError('cloud_assets_manifest_required')
        total = 0
        seen = set()
        for item in manifest['files']:
            name = item.get('path')
            if (set(item) != {'path', 'bytes', 'sha256'} or not isinstance(name, str)
                    or not re.fullmatch(r'[A-Za-z0-9_./-]{1,240}', name) or name.startswith('/')
                    or any(part in ('', '.', '..') for part in name.split('/'))
                    or name in seen or name == 'airi-local-profile.json'
                    or not isinstance(item['bytes'], int) or not 0 < item['bytes'] <= 40 * 1024 * 1024
                    or not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])):
                raise ValueError('cloud_assets_manifest_invalid')
            path = root / name
            if (not path.is_file() or path.is_symlink() or any(p.is_symlink() for p in path.parents)
                    or path.stat().st_size != item['bytes']):
                raise ValueError('cloud_assets_digest_mismatch')
            with path.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != item['sha256']:
                    raise ValueError('cloud_assets_digest_mismatch')
            seen.add(name)
            total += item['bytes']
            if total > 256 * 1024 * 1024:
                raise ValueError('cloud_assets_too_large')
            if name == 'resident.html':
                self.resident = path
            elif path.suffix in SUFFIX_TYPES:
                self.files['/' + name] = path
            else:
                raise ValueError('cloud_asset_type_not_allowed')
        if self.resident is None:
            raise ValueError('cloud_resident_entry_required')

    def response(self, path, *, storage_acceptance, client_id):
        headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'Cross-Origin-Opener-Policy': 'same-origin-allow-popups',
            'Permissions-Policy': 'microphone=(), camera=(), autoplay=()',
            'Content-Security-Policy': "default-src 'none'; script-src 'self' https://accounts.google.com/gsi/client; "
                "style-src 'self' https://accounts.google.com/gsi/style; frame-src 'self' https://accounts.google.com/gsi/; "
                "connect-src 'self' https://accounts.google.com/gsi/; img-src 'self' data: https://*.googleusercontent.com; "
                    "manifest-src 'self'; frame-ancestors 'none'; base-uri 'none'"}
        if not storage_acceptance and self.resident is not None:
            # An ancestor policy cannot be widened by its resident iframe.
            headers['Permissions-Policy'] = 'microphone=(self), camera=(), autoplay=(self)'
        if path == '/login-config':
            return JSONResponse({'client_id': client_id,
                **({'public_resident': True} if self.public_resident and not storage_acceptance else {})}, headers=headers)
        if path == '/cloud/signed-out':
            return HTMLResponse('<p>已登出，請從鄰伴登入頁重新進入。</p>', headers=headers)
        if path in SHELL:
            source, media_type = SHELL[path]
            data = source.read_bytes()
            if path == '/' and self.resident is not None and not storage_acceptance:
                data = data.replace(b'</head>', b'<link rel="manifest" href="/staff.webmanifest"></head>', 1)
                resident = self.resident.read_text(encoding='utf-8')
                entry = re.search(r'name="neighbour-cloud-entry" content="(/assets/[\w-]+\.js)"', resident)
                preloads = []
                if entry and entry[1] in self.files:
                    preloads.append('<link rel="modulepreload" data-neighbour-warm="services" href="' + entry[1] + '">')
                settings = next((name for name in self.files if re.fullmatch(r'/assets/cloud-settings-[\w-]+\.js', name)), None)
                if settings:
                    preloads.append('<link rel="modulepreload" data-neighbour-warm="settings" href="' + settings + '">')
                for kind in ('console', 'fleet'):
                    robot = next(name for name in self.admin.responses if re.fullmatch(r'/cloud/robot-assets/ep-' + kind + r'-[a-f0-9]{12}\.js', name))
                    key = ' data-neighbour-warm="robots"' if kind == 'console' else ''
                    preloads.append('<link rel="modulepreload"' + key + ' href="' + robot + '">')
                for css in re.findall(r'<link rel="stylesheet" crossorigin href="(/assets/[\w-]+\.css)"', resident):
                    if css in self.files:
                        preloads.append('<link rel="preload" as="style" href="' + css + '">')
                data = data.replace(b'</head>', ''.join(preloads).encode() + b'</head>', 1)
            return Response(data, media_type=media_type, headers=headers)
        admin = self.admin.get(path)
        if admin is not None:
            if storage_acceptance:
                return JSONResponse({'detail': '正式資料仍在準備，未開放管理操作。'}, status_code=423, headers=headers)
            headers['Content-Security-Policy'] = (
                "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                "img-src 'self' data: blob:; frame-src 'self'; worker-src 'self'; frame-ancestors 'self'; base-uri 'none'")
            headers['Permissions-Policy'] = 'microphone=(), camera=(), autoplay=(self)'
            if re.fullmatch(r'/cloud/robot-assets/ep-(?:console|fleet)-[a-f0-9]{12}\.js', path):
                headers['Cache-Control'] = 'public, max-age=3600, immutable'
            return Response(admin[0], media_type=admin[1], headers=headers)
        if path in ('/cloud/resident', '/cloud/resident/'):
            if storage_acceptance:
                return JSONResponse({'detail': '正式資料仍在準備，未開放居民對話。'}, status_code=423, headers=headers)
            if self.resident is None:
                return JSONResponse({'detail': '居民畫面仍在準備。'}, status_code=503, headers=headers)
            headers.update({'Permissions-Policy': 'microphone=(self), camera=(), autoplay=(self)',
                'Content-Security-Policy': "default-src 'self'; script-src 'self' blob: 'wasm-unsafe-eval'; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; "
                    "connect-src 'self' data: blob: https://huggingface.co https://*.hf.co https://arweave.net https://*.arweave.net; worker-src 'self' blob:; "
                    "media-src 'self' blob:; frame-src 'none'; frame-ancestors 'self'; base-uri 'none'"})
            data = self.resident.read_bytes().replace(
                b'</head>', b'<link rel="stylesheet" href="/cloud/resident-panel.css"></head>', 1)
            return HTMLResponse(data, headers=headers)
        source = self.files.get(path)
        if source is not None and not storage_acceptance:
            if re.search(r'-[A-Za-z0-9_-]{8,}\.', source.name):
                headers['Cache-Control'] = 'public, max-age=3600'
            return FileResponse(source, media_type=SUFFIX_TYPES[source.suffix], headers=headers)
        return None
