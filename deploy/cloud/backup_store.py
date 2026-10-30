"""Chunked durable SQL backups; never treats host scratch files as authority.

The independent deletion ledger/key are excluded. Publish only a coordinated,
closed eight-store snapshot. Failed/unknown publications remain pending for
inspection; this class never resets counters or automatically restores data.
"""
import hashlib
import hmac
import json
import re
import sqlite3
import tempfile
from contextlib import suppress
from pathlib import Path

from deploy.cloud.closed_backup import unchanged_closed_backup
from deploy.cloud.database_profile import ROLE_FILES
from deploy.cloud.deletion_ledger import canonical
from deploy.cloud.retention_restore import recover

ROLES = frozenset(ROLE_FILES) - {'deletion_ledger'}
TABLES = {'cloud_backup_sets', 'cloud_backup_chunks', 'cloud_backup_receipts'}
CHUNK = 256 * 1024
MAX_FILE = 128 * 1024 * 1024
MAX_TOTAL = 192 * 1024 * 1024
DAY = 86_400_000


class BackupError(ValueError):
    pass


class BackupUncertain(RuntimeError):
    pass


class BackupStore:
    def __init__(self, db, signing_key, *, initialize=False):
        if not isinstance(signing_key, bytes) or not 32 <= len(signing_key) <= 128 or db.in_transaction:
            raise BackupError('dedicated_backup_database_and_key_required')
        self.db, self.key = db, signing_key
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables != TABLES:
            if tables or initialize is not True:
                raise BackupError('backup_database_requires_exact_initialization')
            with db:
                db.execute('CREATE TABLE cloud_backup_sets(id TEXT PRIMARY KEY,created_ms INTEGER NOT NULL,'
                           'status TEXT NOT NULL,manifest TEXT NOT NULL,signature TEXT NOT NULL)')
                db.execute('CREATE TABLE cloud_backup_chunks(backup_id TEXT NOT NULL,role TEXT NOT NULL,'
                           'part INTEGER NOT NULL,content BLOB NOT NULL,PRIMARY KEY(backup_id,role,part))')
                db.execute('CREATE TABLE cloud_backup_receipts(seq INTEGER PRIMARY KEY AUTOINCREMENT,'
                           'backup_id TEXT NOT NULL,at_ms INTEGER NOT NULL,old_signature TEXT NOT NULL,'
                           'new_signature TEXT NOT NULL,operation TEXT NOT NULL)')

    def sign(self, manifest):
        return hmac.new(self.key, ('neighbour-backup-v1:' + canonical(manifest)).encode(), hashlib.sha256).hexdigest()

    def _commit(self):
        try:
            self.db.commit()
        except (OSError, sqlite3.Error):
            with suppress(OSError, sqlite3.Error):
                self.db.rollback()
            raise BackupUncertain('backup_commit_unknown_read_status_before_retry') from None

    def status(self):
        rows = self.db.execute('SELECT id,created_ms,status FROM cloud_backup_sets ORDER BY created_ms DESC').fetchall()
        if any(row[2] not in ('pending', 'ready') for row in rows) or len(rows) > 32:
            raise BackupError('backup_catalog_requires_review')
        return {'completed': sum(row[2] == 'ready' for row in rows),
                'pending': sum(row[2] == 'pending' for row in rows),
                'last_completed_ms': next((row[1] for row in rows if row[2] == 'ready'), None),
                'database_acknowledged': True, 'automatic_restore': False}

    def manifest(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
            raise BackupError('invalid_backup_identity')
        row = self.db.execute('SELECT created_ms,status,manifest,signature FROM cloud_backup_sets WHERE id=?', (identity,)).fetchone()
        if row is None or row[1] != 'ready':
            raise BackupError('completed_backup_required')
        try:
            data = json.loads(row[2])
            if (not isinstance(data, dict) or data.get('format') != 'neighbour-backup-v1'
                    or data.get('id') != identity or data.get('created_ms') != row[0]
                    or data.get('source_fence_verified') is not True or set(data.get('files', {})) != ROLES
                    or not hmac.compare_digest(row[3], self.sign(data))):
                raise ValueError('invalid')
            total = 0
            for item in data['files'].values():
                if (set(item) != {'bytes', 'sha256', 'parts'} or type(item['bytes']) is not int
                        or not 0 < item['bytes'] <= MAX_FILE or not re.fullmatch('[a-f0-9]{64}', item['sha256'])
                        or type(item['parts']) is not int or item['parts'] != (item['bytes'] + CHUNK - 1) // CHUNK):
                    raise ValueError('invalid')
                total += item['bytes']
            if total > MAX_TOTAL:
                raise ValueError('invalid')
        except (ValueError, KeyError, TypeError, AttributeError):
            raise BackupError('backup_manifest_verification_failed') from None
        return data

    def publish(self, identity, files, *, created_ms, ledger_checkpoint, source_fence_verified):
        if (self.db.in_transaction or not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity)
                or type(created_ms) is not int or created_ms < 0 or source_fence_verified is not True
                or not isinstance(files, dict) or set(files) != ROLES
                or not isinstance(ledger_checkpoint, dict) or set(ledger_checkpoint) != {'seq', 'digest', 'signature'}):
            raise BackupError('coordinated_closed_backup_set_required')
        if self.db.execute('SELECT 1 FROM cloud_backup_sets WHERE id=? OR created_ms/?=? LIMIT 1',
                           (identity, DAY, created_ms // DAY)).fetchone():
            raise BackupError('backup_publication_already_exists_review_status')
        manifest = {'format': 'neighbour-backup-v1', 'id': identity, 'created_ms': created_ms,
                    'source_fence_verified': True, 'ledger_checkpoint_at_backup': dict(ledger_checkpoint), 'files': {}}
        total, paths = 0, {}
        for role in sorted(ROLES):
            path = Path(files[role]).absolute()
            if (not path.is_file() or any(p.is_symlink() for p in (path, *path.parents))
                    or not 0 < path.stat().st_size <= MAX_FILE):
                raise BackupError('closed_backup_files_required')
            with path.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            if not unchanged_closed_backup(path, digest):
                raise BackupError('closed_backup_files_required')
            total += path.stat().st_size
            if total > MAX_TOTAL:
                raise BackupError('backup_capacity')
            manifest['files'][role] = {'bytes': path.stat().st_size, 'sha256': digest,
                                       'parts': (path.stat().st_size + CHUNK - 1) // CHUNK}
            paths[role] = path
        # A visible pending set prevents retrying a partially acknowledged day.
        self.db.execute('INSERT INTO cloud_backup_sets VALUES(?,?,?,?,?)',
                        (identity, created_ms, 'pending', canonical(manifest), self.sign(manifest)))
        self._commit()
        try:
            for role, path in paths.items():
                with path.open('rb') as source:
                    for part in range(manifest['files'][role]['parts']):
                        data = source.read(CHUNK)
                        self.db.execute('INSERT INTO cloud_backup_chunks VALUES(?,?,?,?)', (identity, role, part, data))
                        self._commit()
                if not unchanged_closed_backup(path, manifest['files'][role]['sha256']):
                    raise BackupError('backup_source_changed')
            # Read back actual committed remote chunks before advertising ready.
            self._verify_parts(identity, manifest)
            self.db.execute("UPDATE cloud_backup_sets SET status='ready' WHERE id=? AND status='pending'", (identity,))
            self._commit()
            if self.manifest(identity) != manifest:
                raise BackupError('backup_publication_verification_failed')
            return {'completed': True, 'identity': identity, 'bytes': total, 'stores': len(ROLES),
                    'ledger_or_key_included': False, 'source_files_unchanged': True}
        finally:
            if self.db.in_transaction:
                with suppress(OSError, sqlite3.Error):
                    self.db.rollback()

    def _verify_parts(self, identity, manifest, destinations=None):
        if self.db.execute('SELECT COUNT(*) FROM cloud_backup_chunks WHERE backup_id=?', (identity,)).fetchone()[0] != sum(
                item['parts'] for item in manifest['files'].values()):
            raise BackupError('backup_chunk_inventory_failed')
        for role, item in manifest['files'].items():
            digest, size, output = hashlib.sha256(), 0, None
            try:
                if destinations is not None:
                    output = destinations[role].open('xb')
                for part in range(item['parts']):
                    row = self.db.execute('SELECT content FROM cloud_backup_chunks WHERE backup_id=? AND role=? AND part=?',
                                          (identity, role, part)).fetchone()
                    expected = min(CHUNK, item['bytes'] - size)
                    if row is None or not isinstance(row[0], bytes) or len(row[0]) != expected:
                        raise BackupError('backup_chunk_verification_failed')
                    digest.update(row[0])
                    size += len(row[0])
                    if output is not None:
                        output.write(row[0])
                if digest.hexdigest() != item['sha256'] or size != item['bytes']:
                    raise BackupError('backup_chunk_verification_failed')
            finally:
                if output is not None:
                    output.close()

    def download(self, identity, destination):
        """Raw private recovery input only; NOT authorised to replace live stores.

        The caller must reconcile with the CURRENT external erasure ledger and
        merge CURRENT quota/control protections before publishing a new writer.
        """
        manifest = self.manifest(identity)
        path = Path(destination).absolute()
        if path.exists() or not path.parent.is_dir() or any(p.is_symlink() for p in (path, *path.parents)):
            raise BackupError('new_private_recovery_directory_required')
        path.mkdir(mode=0o700)
        with (path / 'INCOMPLETE.json').open('x', encoding='utf-8') as handle:
            json.dump({'cutover_ready': False, 'requires_current_ledger_quota_controls': True}, handle)
        files = {role: path / ROLE_FILES[role][1] for role in ROLES}
        self._verify_parts(identity, manifest, files)
        if self.manifest(identity) != manifest:
            raise BackupError('backup_changed_during_download')
        return {'download_verified': True, 'cutover_ready': False, 'production_replaced': False,
                'files': {role: str(value) for role, value in files.items()}, 'manifest': manifest}

    def reconcile_erasure(self, identity, *, ledger, scratch_root, now_ms, writer_fence):
        """Rewrite still-managed backups against the CURRENT independent ledger.

        Call inside the same live writer barrier as the retention job. The
        checkpoint embedded in an old backup is never accepted as current.
        Source backup bytes and signature are replaced in ONE SQL transaction;
        the old/new signatures remain in the durable receipt table.
        """
        root = Path(scratch_root).absolute()
        if (not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents))
                or type(now_ms) is not int or now_ms < 0 or not callable(writer_fence)
                or writer_fence() is not True or self.db.in_transaction or ledger.db is self.db):
            raise BackupError('independent_live_ledger_and_writer_fence_required')
        old = self.manifest(identity)
        head = ledger.checkpoint()
        ledger.records(head)  # Verify chain now, not only the head signature.
        if old['ledger_checkpoint_at_backup'] == head:
            return {'reconciled': False, 'reason': 'current_ledger_already_applied'}
        with tempfile.TemporaryDirectory(prefix='neighbour-backup-retention-', dir=root) as directory:
            base = Path(directory)
            raw = self.download(identity, base / 'raw')
            replacements, updated = {}, json.loads(json.dumps(old))
            for role in ('cases', 'events', 'photos'):
                path = base / (role + '-reconciled.sqlite3')
                info = recover(raw['files'][role], path, expected_sha256=old['files'][role]['sha256'],
                               ledger=ledger, live_checkpoint=head, scope=role, timeout=120)
                updated['files'][role] = {'bytes': path.stat().st_size, 'sha256': info['sha256'],
                                          'parts': (path.stat().st_size + CHUNK - 1) // CHUNK}
                replacements[role] = path
            updated['ledger_checkpoint_at_backup'] = head
            if (writer_fence() is not True or ledger.checkpoint() != head or self.manifest(identity) != old
                    or sum(item['bytes'] for item in updated['files'].values()) > MAX_TOTAL):
                raise BackupError('backup_retention_source_changed')
            try:
                self.db.execute('BEGIN IMMEDIATE')
                for role, path in replacements.items():
                    self.db.execute('DELETE FROM cloud_backup_chunks WHERE backup_id=? AND role=?', (identity, role))
                    with path.open('rb') as source:
                        for part in range(updated['files'][role]['parts']):
                            self.db.execute('INSERT INTO cloud_backup_chunks VALUES(?,?,?,?)',
                                            (identity, role, part, source.read(CHUNK)))
                self._verify_parts(identity, updated)
                if writer_fence() is not True or ledger.checkpoint() != head:
                    raise BackupError('backup_retention_source_changed')
                prior, signature = self.sign(old), self.sign(updated)
                self.db.execute('UPDATE cloud_backup_sets SET manifest=?,signature=? WHERE id=? AND signature=?',
                                (canonical(updated), signature, identity, prior))
                self.db.execute('INSERT INTO cloud_backup_receipts(backup_id,at_ms,old_signature,new_signature,operation) '
                                'VALUES(?,?,?,?,?)', (identity, now_ms, prior, signature, 'retention_reconcile'))
                self._commit()
            finally:
                if self.db.in_transaction:
                    with suppress(OSError, sqlite3.Error):
                        self.db.rollback()
        if self.manifest(identity) != updated:
            raise BackupError('backup_retention_publication_unverified')
        return {'reconciled': True, 'ledger_sequence': head['seq'], 'original_created_ms': old['created_ms'],
                'usage_controls_memory_unchanged': True, 'durable_receipt': True}

    def rotate(self, *, now_ms, keep=7):
        """Only newly managed completed backups; existing native archives stay.

        This does not replace the separate 90-day erasure reconciliation of
        still-retained backups. A pending/uncertain set blocks rotation.
        """
        if type(now_ms) is not int or now_ms < 0 or type(keep) is not int or not 1 <= keep <= 7 or self.db.in_transaction:
            raise BackupError('bounded_backup_rotation_required')
        rows = self.db.execute('SELECT id,created_ms,status FROM cloud_backup_sets ORDER BY created_ms DESC').fetchall()
        if not rows or any(row[2] != 'ready' for row in rows) or rows[0][1] // DAY != now_ms // DAY:
            raise BackupError('fresh_completed_backup_before_rotation_required')
        selected = [row[0] for row in rows[keep:]]
        for identity in selected:
            self.manifest(identity)
        try:
            self.db.execute('BEGIN IMMEDIATE')
            for identity in selected:
                self.db.execute('DELETE FROM cloud_backup_chunks WHERE backup_id=?', (identity,))
                self.db.execute('DELETE FROM cloud_backup_sets WHERE id=?', (identity,))
                self.db.execute('INSERT INTO cloud_backup_receipts(backup_id,at_ms,old_signature,new_signature,operation) '
                                'VALUES(?,?,?, ?,?)', (identity, now_ms, '', '', 'managed_daily_rotation'))
            self._commit()
        finally:
            if self.db.in_transaction:
                with suppress(OSError, sqlite3.Error):
                    self.db.rollback()
        return {'rotated_managed_backups': len(selected), 'kept': len(rows) - len(selected)}
