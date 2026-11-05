"""Download immutable reviewed application assets, never arbitrary user URLs.

The descriptors include author-specific permission to bundle a character inside
Neighbour. This is not a general model file redistribution or mirroring service.
The caller must require a staff session, preserve notices, and preview only until
the existing explicit Save action publishes through the normal 32/64 MiB store.
No database, credentials, cookie jar, OAuth, or model selection is changed here.
"""
import hashlib
import json
import stat
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx

from .avatar_vrm import MAX_BYTES, validate_vrm

MAX_ARCHIVE_BYTES = 192 * 1024 * 1024
MANIFEST = Path(__file__).with_name('reviewed_model_imports.json')
_HOSTS = {'tyc.rei-yumesaki.net', 'miko.aituberonair.com', 'raw.githubusercontent.com'}


class ReviewedImportUnavailable(ValueError):
    """Small public error codes; upstream pages and paths are never echoed."""


@dataclass(frozen=True)
class ReviewedModel:
    id: str
    name: str
    source: str
    source_name: str
    source_url: str
    license_url: str
    credit: str
    notice: str
    bytes: int
    sha256: str
    download_url: str
    download_bytes: int
    download_sha256: str
    member: str | None = None
    application_only: bool = False

    def public(self):
        return {key: getattr(self, key) for key in (
            'id', 'name', 'source', 'source_name', 'source_url', 'license_url',
            'credit', 'notice', 'bytes', 'sha256', 'application_only')} | {'format': 'vrm'}


def reviewed_models():
    document = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if document.get('version') != 1:
        raise ReviewedImportUnavailable('reviewed_manifest_invalid')
    models = tuple(ReviewedModel(**row) for row in document['models'])
    if len({row.id for row in models}) != len(models):
        raise ReviewedImportUnavailable('reviewed_manifest_invalid')
    for row in models:
        url = urlsplit(row.download_url)
        if (url.scheme != 'https' or url.hostname not in _HOSTS or url.port is not None
                or url.username or url.password or url.query or url.fragment
                or not 28 <= row.bytes <= MAX_BYTES
                or not row.bytes <= row.download_bytes <= MAX_ARCHIVE_BYTES
                or len(row.sha256) != 64 or len(row.download_sha256) != 64
                or any(c not in '0123456789abcdef' for c in row.sha256 + row.download_sha256)
                or (row.member is None and (row.bytes != row.download_bytes
                                            or row.sha256 != row.download_sha256))):
            raise ReviewedImportUnavailable('reviewed_manifest_invalid')
    return models


class ReviewedModelImporter:
    """One bounded public download at a time, with no implicit retry or publish."""

    def __init__(self, *, transport=None, reviewed=None, deadline_seconds=90):
        self._models = {row.id: row for row in (reviewed_models() if reviewed is None else reviewed)}
        self._transport = transport
        self._gate = threading.BoundedSemaphore(1)
        self._deadline_seconds = deadline_seconds

    def catalogue(self):
        return [row.public() for row in self._models.values()]

    def descriptor(self, identity):
        if not isinstance(identity, str) or identity not in self._models:
            raise ReviewedImportUnavailable('model_not_reviewed')
        return self._models[identity]

    def credit(self, model_id):
        if not isinstance(model_id, str) or not model_id.startswith('cloud-vrm-'):
            return None
        digest = model_id.removeprefix('cloud-vrm-')
        row = next((row for row in self._models.values() if row.sha256 == digest), None)
        return {'name': row.name, 'author': row.credit, 'source': row.source_url,
                'terms': row.license_url, 'notice': row.notice} if row else None

    def preview(self, identity):
        """Return unchanged validated VRM bytes. The caller owns staff auth."""
        row = self.descriptor(identity)
        if not self._gate.acquire(blocking=False):
            raise ReviewedImportUnavailable('model_import_busy')
        try:
            end = time.monotonic() + self._deadline_seconds
            # Disk-backed, private, temporary and deleted even after validation
            # errors. The 176 MB official package is never collected in RAM.
            with tempfile.TemporaryFile() as package:
                with (
                    httpx.Client(transport=self._transport, follow_redirects=False,
                                 trust_env=False, timeout=httpx.Timeout(30, connect=15)) as client,
                    client.stream('GET', row.download_url,
                                  headers={'Accept-Encoding': 'identity'}) as response,
                ):
                    if response.status_code != 200:
                        raise ReviewedImportUnavailable('model_download_unavailable')
                    if response.headers.get('content-encoding', 'identity') != 'identity':
                        raise ReviewedImportUnavailable('model_changed_requires_review')
                    length = response.headers.get('content-length')
                    if length is not None and length != str(row.download_bytes):
                        raise ReviewedImportUnavailable('model_changed_requires_review')
                    digest, size = hashlib.sha256(), 0
                    for part in response.iter_bytes(64 * 1024):
                        if time.monotonic() > end:
                            raise ReviewedImportUnavailable('model_download_timeout')
                        size += len(part)
                        if size > row.download_bytes or size > MAX_ARCHIVE_BYTES:
                            raise ReviewedImportUnavailable('model_changed_requires_review')
                        digest.update(part)
                        package.write(part)
                    if size != row.download_bytes or digest.hexdigest() != row.download_sha256:
                        raise ReviewedImportUnavailable('model_changed_requires_review')
                package.seek(0)
                content = self._extract(package, row) if row.member is not None else package.read(MAX_BYTES + 1)
                if len(content) != row.bytes or hashlib.sha256(content).hexdigest() != row.sha256:
                    raise ReviewedImportUnavailable('model_changed_requires_review')
                try:
                    validate_vrm(content)
                except ValueError as error:
                    raise ReviewedImportUnavailable('model_validation_failed') from error
                return content
        except httpx.HTTPError as error:
            raise ReviewedImportUnavailable('model_download_unavailable') from error
        finally:
            self._gate.release()

    @staticmethod
    def _extract(package, row):
        try:
            with zipfile.ZipFile(package) as archive:
                entries = archive.infolist()
                selected = [entry for entry in entries if entry.filename == row.member]
                if len(entries) > 512 or len(selected) != 1:
                    raise ReviewedImportUnavailable('model_archive_invalid')
                entry = selected[0]
                path = PurePosixPath(entry.filename)
                if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename
                        or ':' in entry.filename or '\x00' in entry.filename
                        or entry.flag_bits & 1 or entry.is_dir()
                        or stat.S_ISLNK(entry.external_attr >> 16)
                        or entry.file_size != row.bytes or entry.file_size > MAX_BYTES):
                    raise ReviewedImportUnavailable('model_archive_invalid')
                # Read only the pinned entry, never extractall or execute files.
                with archive.open(entry) as handle:
                    return handle.read(MAX_BYTES + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as error:
            raise ReviewedImportUnavailable('model_archive_invalid') from error
