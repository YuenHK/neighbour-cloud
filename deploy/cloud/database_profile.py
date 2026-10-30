"""Explicit remote-primary connection candidate. Never an automatic local fallback.

The manifest is an operator-provisioned mapping, not evidence that a cloud
account was created, a migration succeeded or the platform can go public.
All production constructors still default to the existing SQLite driver.
"""
import importlib
import json
import math
import re
import sqlite3
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from urllib.parse import parse_qsl, urlsplit
from urllib.request import url2pathname

from deploy.cloud.libsql_connection import Connection

ROLE_FILES = {
    'cases': ('runtime', 'service-desk.sqlite3'),
    'events': ('runtime', 'events.sqlite3'),
    'estate': ('runtime', 'estate-information.sqlite3'),
    'memory': ('runtime', 'assistant-memory.sqlite3'),
    'journal': ('runtime', 'staff-access.sqlite3'),
    'usage': ('settings', 'cloud-usage.sqlite3'),
    'controls': ('settings', 'cloud-control.sqlite3'),
    'photos': ('runtime', 'cloud-photos.sqlite3'),
    'deletion_ledger': ('settings', 'cloud-deletion-ledger.sqlite3'),
}


def verified_format(manifest):
    """Accept the original explicit UI marker or a separate API provenance.

    Both are operator-provisioned attestations, not live billing enforcement.
    API verification must not be relabelled as a UI inspection.
    """
    common = {'format', 'provider', 'plan', 'mode', 'databases'}
    if manifest.get('format') == 'neighbour-cloud-storage-v1':
        return set(manifest) == common | {'ui_verified'} and manifest['ui_verified'] is True
    if manifest.get('format') != 'neighbour-cloud-storage-v2' or set(manifest) != common | {'plan_verification'}:
        return False
    proof = manifest['plan_verification']
    fields = {'source', 'organization', 'plan_id', 'monthly_price', 'overages', 'checked_utc', 'receipt_sha256'}
    if (not isinstance(proof, dict) or set(proof) != fields
            or proof['source'] != 'turso-platform-api'
            or not isinstance(proof['organization'], str)
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', proof['organization'])
            or proof['plan_id'] not in ('starter', 'free') or proof['monthly_price'] != '0'
            or proof['overages'] is not False
            or not isinstance(proof['receipt_sha256'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', proof['receipt_sha256'])
            or not isinstance(proof['checked_utc'], str) or len(proof['checked_utc']) > 40):
        return False
    try:
        checked = datetime.fromisoformat(proof['checked_utc'])
        return checked.tzinfo is not None and checked.utcoffset() == UTC.utcoffset(checked)
    except ValueError:
        return False


def endpoint(value):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme != 'libsql' or not isinstance(host, str)
                or not re.fullmatch(r'[a-z0-9.-]+\.turso\.io', host)
                or parsed.username is not None or parsed.password is not None or parsed.port is not None
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise ValueError('invalid')
    except (ValueError, TypeError, AttributeError):
        raise ValueError('invalid_cloud_database_endpoint') from None
    return 'libsql://' + host


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_cloud_profile_field')
        result[key] = value
    return result


def host_secret():
    from edge_hub import cloud_host_credentials as credentials

    mode = credentials.backend()
    return credentials.decrypt_reference(credentials.reference('turso-data-token', mode=mode))


def host_read_secret():
    from edge_hub import cloud_host_credentials as credentials

    mode = credentials.backend()
    return credentials.decrypt_reference(credentials.reference('turso-read-token', mode=mode))


class DatabaseProfile:
    def __init__(self, manifest, *, runtime_root, settings_root, secret_loader=host_secret,
                 read_secret_loader=host_read_secret, driver_loader=None):
        if (not isinstance(manifest, dict) or not verified_format(manifest)
                or manifest['provider'] != 'turso-libsql' or manifest['plan'] != 'Free'
                or manifest['mode'] != 'remote-primary'
                or not isinstance(manifest['databases'], dict) or set(manifest['databases']) != set(ROLE_FILES)):
            raise ValueError('explicit_complete_free_cloud_database_profile_required')
        roots = {'runtime': Path(runtime_root), 'settings': Path(settings_root)}
        if any(not path.is_absolute() or not path.is_dir() or path.is_symlink() for path in roots.values()):
            raise ValueError('explicit_cloud_database_roots_required')
        if roots['runtime'].resolve() == roots['settings'].resolve():
            raise ValueError('distinct_cloud_database_roots_required')
        bindings = {}
        server_read_only = manifest['format'] == 'neighbour-cloud-storage-v2'
        for role, entry in manifest['databases'].items():
            fields = {'url', 'credential'} | ({'read_credential'} if server_read_only else set())
            if (not isinstance(entry, dict) or set(entry) != fields
                    or entry['credential'] != 'turso-data-token'
                    or (server_read_only and entry['read_credential'] != 'turso-read-token')):
                raise ValueError('invalid_cloud_database_binding')
            bindings[role] = endpoint(entry['url'])
        if len(set(bindings.values())) != len(bindings):
            raise ValueError('distinct_cloud_database_endpoints_required')
        self._bindings = MappingProxyType(bindings)
        self.runtime_root = roots['runtime'].resolve()
        self.settings_root = roots['settings'].resolve()
        self._paths = {str((roots[location] / filename).resolve()): role
                       for role, (location, filename) in ROLE_FILES.items()}
        self._secret_loader = secret_loader
        self._read_secret_loader = read_secret_loader
        self._server_read_only = server_read_only
        self._driver_loader = driver_loader or (lambda: importlib.import_module('libsql'))

    @classmethod
    def from_file(cls, path, **kwargs):
        path = Path(path)
        if (not path.is_absolute() or not path.is_file() or path.is_symlink()
                or any(parent.is_symlink() for parent in path.parents)
                or path.stat().st_size > 32 * 1024):
            raise ValueError('invalid_cloud_profile_file')
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
        except (OSError, ValueError, UnicodeError):
            raise ValueError('invalid_cloud_profile_file') from None
        return cls(manifest, **kwargs)

    def connect(self, database, *, timeout=5, check_same_thread=True, uri=False):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError('bounded_cloud_database_timeout_required')
        if type(uri) is not bool or type(check_same_thread) is not bool:
            raise ValueError('invalid_cloud_database_connection_options')
        read_only = False
        if uri:
            try:
                parsed = urlsplit(str(database))
                options = parse_qsl(parsed.query, keep_blank_values=True)
                if (parsed.scheme != 'file' or parsed.netloc or parsed.fragment
                        or options not in ([('mode', 'ro')], [('mode', 'rw')])):
                    raise ValueError('invalid')
                read_only = options == [('mode', 'ro')]
                database = url2pathname(parsed.path)
            except (ValueError, TypeError):
                raise ValueError('invalid_cloud_database_file_uri') from None
        path = Path(database)
        if (not path.is_absolute() or path.is_symlink()
                or any(parent.is_symlink() for parent in path.parents)
                or (path.exists() and path.stat().st_size > 0)):
            raise ValueError('cloud_database_path_requires_review')
        role = self._paths.get(str(path.resolve()))
        if role is None:
            raise ValueError('unbound_cloud_database_path')
        try:
            loader = self._read_secret_loader if read_only and self._server_read_only else self._secret_loader
            raw_key = loader()
            if (not isinstance(raw_key, bytes) or not 16 <= len(raw_key) <= 4096
                    or not raw_key.isascii() or any(value <= 32 or value == 127 for value in raw_key)):
                raise ValueError('invalid')
            key = raw_key.decode('ascii')
        except (OSError, ValueError, RuntimeError, LookupError, TypeError):
            raise ValueError('cloud_database_credential_unavailable') from None
        raw = None
        errors = (ImportError, OSError, ValueError, RuntimeError, TypeError, AttributeError, sqlite3.Error)
        try:
            driver = self._driver_loader()
            if not isinstance(driver.Error, type) or not issubclass(driver.Error, Exception):
                raise TypeError('invalid_cloud_database_driver')
            errors = (*errors, driver.Error)
            raw = driver.connect(self._bindings[role], timeout=timeout,
                                 _check_same_thread=check_same_thread, auth_token=key)
            connection = Connection(raw, driver.Error)
            # Real Turso rejects PRAGMA query_only. V2 uses a separately minted
            # provider-enforced read-only token, never falls back to the writer.
            # V1 remains supported for previous explicitly provisioned profiles.
            if read_only and not self._server_read_only:
                connection.execute('PRAGMA query_only=ON')
            return connection
        except errors:
            if raw is not None:
                with suppress(*errors):
                    raw.close()
            raise ValueError('cloud_database_connection_unavailable') from None
