"""Explicit ASGI factory for the cloud API, with no import-time activation.

This does not provision a host, enrol Google identities, serve the frontend,
migrate data, establish a single writer, or declare public readiness. The
operator must supply reviewed metadata and an already imported remote profile.
Native services and their credential defaults are not changed.
"""
import asyncio
import base64
import json
import os
import re
import sqlite3
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from starlette.responses import JSONResponse

from deploy.cloud.bootstrap import open_services
from deploy.cloud.database_profile import DatabaseProfile, unique_object
from deploy.cloud.google_identity import GoogleIdentityVerifier
from deploy.cloud.http_app import create_app, validate_origin
from edge_hub import cloud_host_credentials as credentials


class HostConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class HostConfiguration:
    origin: str
    google_client_id: str
    accounts: object
    database_profile: Path
    runtime_root: Path
    settings_root: Path
    scratch_root: Path
    backend: str


def checked_path(value, *, directory=False):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError('invalid_path')
    path = Path(value)
    if (not path.is_absolute() or path == path.parent or path.is_symlink()
            or any(parent.is_symlink() for parent in path.parents)
            or (not path.is_dir() if directory else not path.is_file())):
        raise ValueError('invalid_path')
    return path.resolve()


def read_configuration():
    try:
        config = checked_path(os.environ.get('NEIGHBOUR_CLOUD_CONFIG'))
        with config.open('rb') as source:
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError('oversized_configuration')
        info = json.loads(raw, object_pairs_hook=unique_object)
        fields = {'format', 'origin', 'google_client_id', 'accounts', 'database_profile',
                  'runtime_root', 'settings_root', 'scratch_root'}
        if (not isinstance(info, dict) or set(info) != fields
                or info['format'] != 'neighbour-cloud-host-v1'):
            raise ValueError('invalid_configuration')
        validate_origin(info['origin'])
        client, accounts = info['google_client_id'], info['accounts']
        if (not isinstance(client, str) or len(client) > 256
                or not re.fullmatch(r'[0-9]+(?:-[A-Za-z0-9_-]+)?\.apps\.googleusercontent\.com', client)
                or not isinstance(accounts, dict) or not 1 <= len(accounts) <= 100
                or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,255}', subject)
                       or role not in ('staff', 'resident') for subject, role in accounts.items())
                or 'staff' not in accounts.values()):
            raise ValueError('invalid_identity_configuration')
        profile = checked_path(info['database_profile'])
        roots = [checked_path(info[name], directory=True)
                 for name in ('runtime_root', 'settings_root', 'scratch_root')]
        backend = credentials.backend()
        if (backend not in ('systemd', 'managed-environment') or len(set(roots)) != 3
                or credentials.settings_directory().resolve() != roots[1]):
            raise ValueError('explicit_cloud_backend_required')
        return HostConfiguration(info['origin'], client, MappingProxyType(dict(accounts)),
                                 profile, *roots, backend)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, UnicodeError):
        raise HostConfigurationError('cloud_host_configuration_required') from None


def ledger_key():
    """Host secrets carry an explicit base64 envelope, not a replacement key.

    The original signed deletion ledger can use arbitrary binary key bytes.
    Using the base64 text itself would invalidate all existing receipts.
    """
    try:
        value = credentials.decrypt_reference(credentials.reference(
            'retention-ledger-key', mode=credentials.backend()))
        if not value.startswith(b'base64:'):
            raise ValueError('missing_encoding')
        key = base64.b64decode(value[7:], validate=True)
        if not 32 <= len(key) <= 128:
            raise ValueError('invalid_key_length')
        return key
    except (OSError, ValueError, RuntimeError, TypeError):
        raise HostConfigurationError('cloud_ledger_credential_unavailable') from None


class CloudHost:
    def __init__(self, config):
        self.config = config
        self.application = None
        self._started_once = False
        self._services = None
        self.cleanup_failed = False

    def _close(self):
        if self._services is not None:
            try:
                self._services.close()
            except (OSError, RuntimeError, ValueError, sqlite3.Error):
                self.cleanup_failed = True
            finally:
                self._services = None

    def _assemble(self, config):
        # Never let a later environment change silently select native DPAPI.
        if (credentials.backend() != config.backend
                or credentials.settings_directory().resolve() != config.settings_root):
            raise HostConfigurationError('cloud_host_configuration_changed')
        verifier = GoogleIdentityVerifier(config.google_client_id, dict(config.accounts))
        profile = DatabaseProfile.from_file(config.database_profile,
            runtime_root=config.runtime_root, settings_root=config.settings_root)
        self._services = open_services(profile, signing_key_loader=ledger_key,
                                       scratch_root=config.scratch_root, timeout=60)
        try:
            return create_app(self._services, verifier, origin=config.origin)
        except BaseException:
            self._close()
            raise

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'lifespan':
            if self.application is not None:
                return await self.application(scope, receive, send)
            if scope['type'] == 'http':
                return await JSONResponse({'detail': '服務尚未完成啟動。'}, status_code=503,
                    headers={'Cache-Control': 'no-store'})(scope, receive, send)
            if scope['type'] == 'websocket':
                return await send({'type': 'websocket.close', 'code': 1008})
            return
        if self._started_once:
            await send({'type': 'lifespan.startup.failed', 'message': 'cloud_host_already_started'})
            raise RuntimeError('cloud_host_already_started')
        self._started_once = True
        initial = await receive()
        if initial.get('type') != 'lifespan.startup':
            await send({'type': 'lifespan.startup.failed', 'message': 'cloud_host_startup_required'})
            raise RuntimeError('cloud_host_startup_required')
        try:
            # Await completion instead of abandoning a thread with open DBs if
            # startup is cancelled. No request is accepted as ready meanwhile.
            building = asyncio.create_task(asyncio.to_thread(self._assemble, self.config))
            try:
                self.application = await asyncio.shield(building)
            except asyncio.CancelledError:
                with suppress(Exception):
                    await building
                raise
            first = True

            async def replay():
                nonlocal first
                if first:
                    first = False
                    return initial
                return await receive()

            await self.application(scope, replay, send)
        except Exception:
            # The API's own lifespan may have already sent startup.failed or
            # raised after a shutdown message. Do not emit a second ASGI reply.
            if self.application is None:
                await send({'type': 'lifespan.startup.failed', 'message': 'cloud_host_startup_unavailable'})
                raise RuntimeError('cloud_host_startup_unavailable') from None
            else:
                raise
        finally:
            self.application = None
            self._close()


def create_host():
    """Uvicorn --factory entry; validates metadata without opening a DB."""
    return CloudHost(read_configuration())
