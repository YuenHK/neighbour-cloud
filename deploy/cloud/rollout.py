"""One-release stopped-writer handover; no schema creation or default permit.

Render can route to this maintenance-only process before the previous process
exits. Full application startup is deferred until an operator records a signed
stop receipt. The waiting process only uses the supplier's read-only token.
This is not a distributed lease for concurrent future deployments.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import sqlite3
from contextlib import closing, suppress
from datetime import datetime
from pathlib import Path

from starlette.responses import JSONResponse, Response

SERVICE = 'srv-dbii3qijnfac73cgabd0'
RELEASE = 'viewport-fit-20261105-barrier30'
RECORD = hashlib.sha256(('rollout:' + RELEASE).encode()).hexdigest()
DOMAIN = b'neighbour-stopped-writer-rollout-v1\0'
FIELDS = {'format', 'release', 'service_id', 'stop_event_id', 'stopped_instance',
          'stopped_at_utc', 'approved_utc', 'signature'}
log = logging.getLogger(__name__)


def canonical(value):
    return json.dumps({key: item for key, item in value.items() if key != 'signature'},
                      sort_keys=True, separators=(',', ':')).encode()


def approved(raw, key):
    """Missing, malformed, foreign or unsigned rows never permit startup."""
    try:
        value = json.loads(raw)
        if (set(value) != FIELDS or value['format'] != 'neighbour-stopped-writer-v1'
                or value['release'] != RELEASE or value['service_id'] != SERVICE
                or not isinstance(value['stop_event_id'], str) or not value['stop_event_id'].startswith('evt-')
                or not isinstance(value['stopped_instance'], str)
                or not value['stopped_instance'].startswith(SERVICE + '-')
                or not isinstance(value['signature'], str)):
            return False
        stopped = datetime.fromisoformat(value['stopped_at_utc'])
        stamped = datetime.fromisoformat(value['approved_utc'])
        if stopped.utcoffset() is None or stamped.utcoffset() is None or stamped < stopped:
            return False
        expected = hmac.new(key, DOMAIN + canonical(value), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, value['signature'])
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def permission_reader(host):
    import importlib

    from deploy.cloud.host import ledger_key
    from deploy.cloud.libsql_connection import Connection
    from edge_hub import cloud_host_credentials as credentials

    config = host.config
    if not isinstance(host.release, dict) or 'backup_url' not in host.release:
        raise ValueError('formal_release_required_for_rollout')

    def read():
        driver = importlib.import_module('libsql')
        key = credentials.decrypt_reference(credentials.reference('turso-read-token', mode=config.backend))
        with closing(Connection(driver.connect(host.release['backup_url'],
                     auth_token=key.decode('ascii'), timeout=5), driver.Error)) as db:
            row = db.execute('SELECT summary FROM cloud_release_probes '
                "WHERE release_sha256=? AND state='rollout-approved'", (RECORD,)).fetchone()
        return row is not None and approved(row[0], ledger_key())

    return read


class RolloutHost:
    def __init__(self, host, read, *, interval=5):
        self.host, self.read, self.interval = host, read, interval
        self.ready = False
        self.activation_started = False
        self.failed = False
        self.inner = None
        self.queue = None

    async def _wait(self):
        while not self.activation_started:
            worker = asyncio.create_task(asyncio.to_thread(self.read))
            try:
                allowed = await asyncio.shield(worker)
            except asyncio.CancelledError:
                with suppress(Exception):
                    await worker
                raise
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                allowed = False
            if not allowed:
                await asyncio.sleep(self.interval)
                continue
            self.activation_started = True
            log.warning('rollout_stop_receipt_accepted')
            self.queue = asyncio.Queue()
            await self.queue.put({'type': 'lifespan.startup'})

            async def sent(message):
                if message['type'] == 'lifespan.startup.complete':
                    self.ready = True
                    log.warning('rollout_application_ready')
                elif message['type'] == 'lifespan.startup.failed':
                    self.failed = True

            try:
                await self.host({'type': 'lifespan', 'asgi': {'version': '3.0'}}, self.queue.get, sent)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.ready = False
                self.failed = True
                log.error('rollout_application_startup_failed')
            finally:
                self.ready = False

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            message = await receive()
            if message['type'] != 'lifespan.startup':
                raise RuntimeError('rollout_lifespan_startup_required')
            self.inner = asyncio.create_task(self._wait())
            # Only the maintenance shell is ready. /health remains 503 until
            # the real application's own startup has actually completed.
            await send({'type': 'lifespan.startup.complete'})
            try:
                message = await receive()
                if message['type'] != 'lifespan.shutdown':
                    raise RuntimeError('rollout_lifespan_shutdown_required')
            finally:
                self.ready = False
                if self.activation_started and self.queue is not None:
                    await self.queue.put({'type': 'lifespan.shutdown'})
                else:
                    self.inner.cancel()
                with suppress(asyncio.CancelledError):
                    await self.inner
            return await send({'type': 'lifespan.shutdown.complete'})
        if self.ready:
            return await self.host(scope, receive, send)
        if scope['type'] == 'websocket':
            return await send({'type': 'websocket.close', 'code': 1013})
        if scope['type'] == 'http':
            # Free-host cold starts are normal, not an unfinished deployment.
            # Serve only a public waiting document and its inert assets until
            # the real application has completed startup. APIs stay closed.
            boot_files = {'/': ('boot-wait.html', 'text/html'),
                '/cloud/boot-wait.js': ('boot-wait.js', 'text/javascript'),
                '/cloud/boot-wait.css': ('boot-wait.css', 'text/css'),
                '/cloud/community-systems.js': ('community-systems.js', 'text/javascript'),
                '/cloud/community-state.js': ('community-state.js', 'text/javascript'),
                '/cloud/community-products.js': ('community-products.js', 'text/javascript'),
                '/cloud/community-systems.css': ('community-systems.css', 'text/css'),
                '/cloud/mascot.css': ('mascot.css', 'text/css'),
                '/assets/brand/neighbour-house-apricot-v1.webp': ('brand/neighbour-house-apricot-v1.webp', 'image/webp'),
                '/assets/brand/favicon-32.png': ('brand/favicon-32.png', 'image/png')}
            boot = boot_files.get(scope.get('path'))
            if scope.get('method') in ('GET', 'HEAD') and boot:
                return await Response((Path(__file__).with_name('web') / boot[0]).read_bytes(),
                    media_type=boot[1], headers={'Cache-Control': 'no-store',
                        'X-Content-Type-Options': 'nosniff',
                        'Permissions-Policy': 'microphone=(), camera=(), autoplay=()',
                        'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; "
                            "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'"})(scope, receive, send)
            return await JSONResponse({'detail': ('服務暫時未能啟動，請稍後再試。' if self.failed else '正在啟動服務，請稍後再試。' if self.activation_started else '服務更新中，請稍後再試。'),
                'public_ready': False, 'rollout_waiting': not self.activation_started,
                'rollout_failed': self.failed, 'rollout_release': RELEASE,
                'rollout_phase': 'failed' if self.failed else 'starting' if self.activation_started else 'waiting'}, status_code=503,
                headers={'Cache-Control': 'no-store', 'Retry-After': '15'})(scope, receive, send)


def create_host():
    from deploy.cloud.host import create_host as deferred_host

    host = deferred_host()  # Validates metadata; does NOT open application DBs.
    return RolloutHost(host, permission_reader(host))
