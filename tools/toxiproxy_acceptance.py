"""Pinned official Toxiproxy, localhost-only transport faults, no formal API.

Release binary must match GitHub's SHA256 asset digest. Security-blocked
downloads are failures, never bypassed. Processes/ports are owned by this run.
"""
import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

VERSION = '2.13.0'
# Recorded from this fixed official release's SHA256 asset digest. Reusing a
# verified tool must not depend on a fresh GitHub metadata request every run.
REVIEWED_DIGESTS = {
    'toxiproxy-server-windows-amd64.exe': '04b710eefd7690c89f7cc67289e3e14618f1ff3c26e4a5f752a34a879b895bab',
}


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def binary(root):
    system = 'windows' if os.name == 'nt' else 'linux'
    if platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('unsupported_test_architecture')
    filename = f'toxiproxy-server-{system}-amd64' + ('.exe' if system == 'windows' else '')
    release_url = f'https://github.com/Shopify/toxiproxy/releases/tag/v{VERSION}'
    digest = REVIEWED_DIGESTS.get(filename)
    download_url = f'https://github.com/Shopify/toxiproxy/releases/download/v{VERSION}/{filename}'
    if digest is None:
        request = urllib.request.Request(f'https://api.github.com/repos/Shopify/toxiproxy/releases/tags/v{VERSION}', headers={'User-Agent': 'neighbour-isolated-acceptance'})
        with urllib.request.urlopen(request, timeout=20) as response:
            release = json.load(response)
        asset = next(item for item in release['assets'] if item['name'] == filename)
        advertised = asset.get('digest', '')
        if not advertised.startswith('sha256:') or len(advertised) != 71:
            raise ValueError('official_asset_digest_required')
        digest, download_url = advertised[7:], asset['browser_download_url']
    destination = root / filename
    root.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        with urllib.request.urlopen(download_url, timeout=60) as response:
            data = response.read(30_000_001)
        if len(data) > 30_000_000 or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('toxiproxy_digest_mismatch')
        destination.write_bytes(data)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError('toxiproxy_digest_mismatch')
    if os.name != 'nt':
        destination.chmod(0o700)
    (root / 'SOURCE.json').write_text(json.dumps({'repository': release_url, 'version': VERSION,
        'asset': filename, 'sha256': digest, 'license': 'MIT'}, indent=2))
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    exe = binary(output.parent / 'toxiproxy')
    api_port, proxy_port = free_port(), free_port()

    class Synthetic(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '12000')
            self.end_headers()
            try:
                self.wfile.write(b'x' * 12000)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Synthetic)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with (output.parent / 'toxiproxy.log').open('wb') as log:
        process = subprocess.Popen([str(exe), '-host', '127.0.0.1', '-port', str(api_port)], stdout=log,
            stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                api = f'http://127.0.0.1:{api_port}'
                for _ in range(100):
                    try:
                        if client.get(api + '/version').is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.05)
                else:
                    raise RuntimeError('toxiproxy_not_started')
                client.post(api + '/proxies', json={'name': 'synthetic', 'listen': f'127.0.0.1:{proxy_port}',
                    'upstream': f'127.0.0.1:{server.server_port}', 'enabled': True}).raise_for_status()
                url = f'http://127.0.0.1:{proxy_port}/synthetic-only'
                assert client.get(url).content == b'x' * 12000
                toxic = api + '/proxies/synthetic/toxics'
                client.post(toxic, json={'name': 'delay', 'type': 'latency', 'stream': 'downstream',
                    'attributes': {'latency': 300, 'jitter': 0}}).raise_for_status()
                started = time.monotonic()
                assert client.get(url).status_code == 200
                delay_ms = (time.monotonic()-started)*1000
                assert delay_ms >= 250
                client.delete(toxic + '/delay').raise_for_status()
                client.post(toxic, json={'name': 'truncate', 'type': 'limit_data', 'stream': 'downstream',
                    'attributes': {'bytes': 500}}).raise_for_status()
                failed = False
                try:
                    client.get(url)
                except httpx.HTTPError:
                    failed = True
                assert failed, 'truncated response must not count as success'
                client.delete(toxic + '/truncate').raise_for_status()
                assert client.get(url).content == b'x' * 12000
                output.write_text(json.dumps({'passed': True, 'latency_ms': round(delay_ms),
                    'truncated_body_rejected': True, 'recovered': True, 'scope': 'localhost_synthetic_transport_only'}, indent=2))
        finally:
            process.terminate()
            process.wait(timeout=10)
            server.shutdown()
            server.server_close()
    print(json.dumps({'passed': True, 'report': str(output)}))


if __name__ == '__main__':
    main()
