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
    '/': (WEB / 'index.html', 'text/html'),
    '/cloud/shell.js': (WEB / 'shell.js', 'text/javascript'),
    '/cloud/shell.css': (WEB / 'shell.css', 'text/css'),
    '/cloud/launch-screen.js': (WEB / 'launch-screen.js', 'text/javascript'),
    '/cloud/launch-screen.css': (WEB / 'launch-screen.css', 'text/css'),
    '/cloud/frame-entry.js': (WEB / 'frame-entry.js', 'text/javascript'),
    '/cloud/admin-entry.js': (WEB / 'admin-entry.js', 'text/javascript'),
    '/cloud/robot-entry.js': (WEB / 'robot-entry.js', 'text/javascript'),
    '/cloud/admin-request.js': (WEB / 'admin-request.js', 'text/javascript'),
    '/cloud/cloud-session.js': (OVERLAY / 'cloud-session.js', 'text/javascript'),
    '/cloud/cloud-frame.js': (OVERLAY / 'cloud-frame.js', 'text/javascript'),
    '/cloud/cloud-transport.js': (OVERLAY / 'cloud-transport.js', 'text/javascript'),
    '/cloud/resident-recovery.js': (OVERLAY / 'resident-recovery.js', 'text/javascript'),
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
            if total > 200 * 1024 * 1024:
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
                "frame-ancestors 'none'; base-uri 'none'"}
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
                resident = self.resident.read_text(encoding='utf-8')
                entry = re.search(r'name="neighbour-cloud-entry" content="(/assets/[\w-]+\.js)"', resident)
                preloads = []
                if entry and entry[1] in self.files:
                    preloads.append('<link rel="modulepreload" href="' + entry[1] + '">')
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
                "img-src 'self' data: blob:; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'")
            headers['Permissions-Policy'] = 'microphone=(), camera=(), autoplay=(self)'
            return Response(admin[0], media_type=admin[1], headers=headers)
        if path in ('/cloud/resident', '/cloud/resident/'):
            if storage_acceptance:
                return JSONResponse({'detail': '正式資料仍在準備，未開放居民對話。'}, status_code=423, headers=headers)
            if self.resident is None:
                return JSONResponse({'detail': '居民畫面仍在準備。'}, status_code=503, headers=headers)
            headers.update({'Permissions-Policy': 'microphone=(self), camera=(), autoplay=(self)',
                'Content-Security-Policy': "default-src 'self'; script-src 'self' blob: 'wasm-unsafe-eval'; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; "
                    "connect-src 'self' data: blob: https://huggingface.co https://*.hf.co; worker-src 'self' blob:; "
                    "media-src 'self' blob:; frame-src 'none'; frame-ancestors 'self'; base-uri 'none'"})
            return HTMLResponse(self.resident.read_bytes(), headers=headers)
        source = self.files.get(path)
        if source is not None and not storage_acceptance:
            if re.search(r'-[A-Za-z0-9_-]{8,}\.', source.name):
                headers['Cache-Control'] = 'public, max-age=3600'
            return FileResponse(source, media_type=SUFFIX_TYPES[source.suffix], headers=headers)
        return None
