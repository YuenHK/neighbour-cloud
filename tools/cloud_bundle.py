"""Build a source-only cloud preparation bundle without runtime/user data.

This is not a running cloud deployment, Linux installer, data migration or a
complete AIRI build. The manifest says exactly which assets are still needed.
"""
import argparse
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path

TREES = {'edge_hub': {'.py', '.html', '.js', '.css', '.svg'},
         'local_audio_gateway': {'.py', '.txt'},
         'airi_overlay': {'.py', '.ts', '.js', '.vue', '.css', '.json'},
         'airi_bridge': {'.ts', '.json'},
         'contracts': {'.json'},
         'deploy/cloud': {'.py', '.md', '.json', '.txt', '.service', '.html', '.js', '.css', '.svg'}}
ROOT_FILES = ('pyproject.toml', 'package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml')
TOOLS = ('tools/cloud_bundle.py', 'tools/cloud_preflight.py', 'tools/cloud_frontend_assets.py')
FORBIDDEN = {'.git', '.runtime', '.experiments', '.venv', '.venv-audio', 'node_modules',
             '__pycache__', '.env', 'data', 'output'}
PRIVATE_SUFFIXES = {'.dpapi', '.sqlite3', '.sqlite', '.db', '.wav', '.mp3', '.log', '.pem', '.key'}
OBVIOUS_SECRET = re.compile(
    rb'AIza[0-9A-Za-z_-]{35}|tvly-[0-9A-Za-z_-]{24,}|sk-ant-api[0-9A-Za-z_-]{24,}'
    rb'|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')


def source_files(root):
    root = Path(root).resolve(strict=True)
    for name, suffixes in TREES.items():
        directory = root / name
        if not directory.exists():
            continue
        if directory.is_symlink():
            raise ValueError('Source symlinks are not supported')
        for parent, directories, names in os.walk(directory, followlinks=False):
            base = Path(parent)
            directories[:] = sorted(item for item in directories if item not in FORBIDDEN)
            for item in directories + names:
                if (base / item).is_symlink():
                    raise ValueError('Source symlinks are not supported')
            for item in sorted(names):
                path = base / item
                if (item in FORBIDDEN or path.suffix in PRIVATE_SUFFIXES
                        or path.suffix not in suffixes or item.endswith('.tsbuildinfo')):
                    continue
                yield path.relative_to(root), path
    for name in ROOT_FILES + TOOLS:
        path = root / name
        if path.is_symlink():
            raise ValueError('Source symlinks are not supported')
        if path.is_file():
            yield Path(name), path


def build(root, output):
    root, output = Path(root).resolve(strict=True), Path(output).absolute()
    files = sorted(source_files(root), key=lambda item: item[0].as_posix())
    if not files or not (root / 'edge_hub/app.py').is_file():
        raise ValueError('A complete project source root is required')
    contents = []
    for relative, path in files:
        data = path.read_bytes()
        if len(data) > 16 * 1024 * 1024:
            raise ValueError('Unexpected oversized source file')
        if OBVIOUS_SECRET.search(data):
            # This is a secondary guard, not a claim to detect every possible
            # secret. The primary boundary is the explicit source allowlist.
            raise ValueError('Credential-like source content requires review')
        contents.append((relative.as_posix(), data))
    manifest = {'format': 'neighbour-cloud-preparation-v1', 'kind': 'source-only',
                'deployed': False, 'contains_resident_data': False, 'contains_credentials': False,
                'requires': ['Linux host', 'reviewed isolated AIRI cloud asset manifest',
                             'approved free Cloudflare Whisper configuration', 'explicit data cutover with usage counters',
                             'private service credentials', 'authenticated HTTPS ingress',
                             'off-Notebook end-to-end acceptance'], 'files': []}
    # Exclusive creation: never overwrite an earlier export or backup.
    with (output.open('xb') as handle,
          zipfile.ZipFile(handle, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive):
        for name, data in contents:
            # Canonical ZIP timestamps make equal source inputs reproducible.
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
            manifest['files'].append({'path': name, 'bytes': len(data),
                                      'sha256': hashlib.sha256(data).hexdigest()})
        info = zipfile.ZipInfo('CLOUD-BUNDLE.json', date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, json.dumps(manifest, ensure_ascii=False, indent=2))
    return {'file_count': len(files), 'bytes': output.stat().st_size,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'deployed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.output)))


if __name__ == '__main__':
    main()
