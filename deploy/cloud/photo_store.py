"""Bounded durable-photo candidate for SQL-backed cloud hosting.

Only synthetic photos are used in tests. This module is not wired into the live
patrol or staff routes. A real cloud restore must also apply the latest external
retention receipts; restoring an old entire DB alone would roll back tombstones.
"""
import hashlib
import io
import re
import threading
from contextlib import contextmanager

from PIL import Image

DAY = 86_400_000
MAX_IMAGE = 1_500_000


def valid_key(key):
    return (isinstance(key, str) and len(key) <= 240
            and re.fullmatch(r'events/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:jpg|jpeg|png)', key))


def validate_image(image, expected):
    if not isinstance(image, bytes) or not 0 < len(image) <= MAX_IMAGE:
        raise ValueError('invalid_cloud_photo')
    try:
        with Image.open(io.BytesIO(image)) as photo:
            if (photo.format != expected or not 0 < photo.width <= 2560 or not 0 < photo.height <= 2560
                    or photo.width * photo.height > 2560 * 1440):
                raise ValueError('invalid_cloud_photo')
            photo.verify()
    except (OSError, SyntaxError, Image.DecompressionBombError):
        raise ValueError('invalid_cloud_photo') from None


class PhotoStore:
    def __init__(self, connection, *, max_bytes=512 * 1024 * 1024, initialize=True):
        if (type(max_bytes) is not int or not 0 < max_bytes <= 2 * 1024 * 1024 * 1024
                or type(initialize) is not bool):
            raise ValueError('invalid_cloud_photo_budget')
        self.db, self.max_bytes = connection, max_bytes
        self.lock = threading.RLock()
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('cloud_deletion_receipts','cloud_deletion_head')").fetchone():
            raise ValueError('cloud_photos_require_separate_deletion_ledger')
        if not initialize:
            return
        with self.transaction():
            self.db.execute('CREATE TABLE IF NOT EXISTS cloud_photos('
                            'key TEXT PRIMARY KEY,event_id TEXT NOT NULL,side TEXT NOT NULL,'
                            'digest TEXT NOT NULL,content BLOB NOT NULL,created_ms INTEGER NOT NULL,'
                            'UNIQUE(event_id,side))')
            self.db.execute('CREATE TABLE IF NOT EXISTS cloud_photo_tombstones('
                            'key TEXT PRIMARY KEY,event_id TEXT NOT NULL,erased_ms INTEGER NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS cloud_photo_retention('
                            'event_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,'
                            'status TEXT NOT NULL,completed_ms INTEGER)')
            self.db.execute('CREATE TABLE IF NOT EXISTS cloud_erased_events('
                            'event_id TEXT PRIMARY KEY,erased_ms INTEGER NOT NULL)')

    @contextmanager
    def transaction(self):
        with self.lock:
            if self.db.in_transaction:
                # Joining is deliberate. The outer case/event transaction owns
                # commit and rollback; never commit it inside this store.
                yield
            else:
                with self.db:
                    self.db.execute('BEGIN IMMEDIATE')
                    yield

    def put(self, event_id, side, key, image, *, reviewed, now_ms):
        if (not isinstance(event_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', event_id)
                or side not in ('event', 'left', 'right') or not valid_key(key)
                or reviewed is not True or type(now_ms) is not int or now_ms < 0):
            raise ValueError('cloud_photo_requires_bound_reviewed_input')
        validate_image(image, 'PNG' if key.endswith('.png') else 'JPEG')
        digest = hashlib.sha256(image).hexdigest()
        with self.transaction():
            if self.db.execute('SELECT 1 FROM cloud_erased_events WHERE event_id=?', (event_id,)).fetchone():
                raise ValueError('cloud_photo_event_was_erased')
            if self.db.execute('SELECT 1 FROM cloud_photo_tombstones WHERE key=?', (key,)).fetchone():
                raise ValueError('cloud_photo_was_erased')
            old = self.db.execute('SELECT event_id,side,digest,content FROM cloud_photos WHERE key=?', (key,)).fetchone()
            if old:
                if tuple(old[:3]) != (event_id, side, digest) or old[3] != image:
                    raise ValueError('cloud_photo_is_immutable')
                return {'key': key, 'sha256': digest, 'replayed': True}
            state = self.db.execute('SELECT status FROM cloud_photo_retention WHERE event_id=?', (event_id,)).fetchone()
            if state and state[0] in ('resolved', 'false_positive'):
                raise ValueError('cloud_photo_event_already_completed')
            used = self.db.execute('SELECT COALESCE(SUM(LENGTH(content)),0) FROM cloud_photos').fetchone()[0]
            if used + len(image) > self.max_bytes:
                raise ValueError('cloud_photo_budget_reached')
            self.db.execute('INSERT INTO cloud_photos VALUES(?,?,?,?,?,?)', (key, event_id, side, digest, image, now_ms))
        return {'key': key, 'sha256': digest, 'replayed': False}

    def get(self, key):
        if not valid_key(key):
            raise ValueError('invalid_cloud_photo_key')
        with self.lock:
            row = self.db.execute('SELECT digest,content FROM cloud_photos p WHERE key=? AND NOT EXISTS '
                                 '(SELECT 1 FROM cloud_erased_events e WHERE e.event_id=p.event_id)', (key,)).fetchone()
            if not row:
                raise KeyError('cloud_photo_not_available')
            if not isinstance(row[1], bytes) or hashlib.sha256(row[1]).hexdigest() != row[0]:
                raise ValueError('cloud_photo_integrity_failed')
            validate_image(row[1], 'PNG' if key.endswith('.png') else 'JPEG')
            return row[1]

    def event_state(self, event_id, status, revision, *, completed_ms=None):
        if (not isinstance(event_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', event_id)
                or type(revision) is not int or revision < 1
                or status not in ('pending', 'confirmed', 'resolved', 'false_positive')
                or (status in ('resolved', 'false_positive')
                    and (type(completed_ms) is not int or completed_ms < 0))
                or (status not in ('resolved', 'false_positive') and completed_ms is not None)):
            raise ValueError('invalid_cloud_photo_event_state')
        with self.transaction():
            if self.db.execute('SELECT 1 FROM cloud_erased_events WHERE event_id=?', (event_id,)).fetchone():
                raise ValueError('cloud_photo_event_was_erased')
            old = self.db.execute('SELECT revision,status,completed_ms FROM cloud_photo_retention WHERE event_id=?', (event_id,)).fetchone()
            if old:
                if tuple(old) == (revision, status, completed_ms):
                    return
                if revision <= old[0]:
                    raise ValueError('stale_cloud_photo_event_state')
                if (old[1] in ('resolved', 'false_positive') and status in ('resolved', 'false_positive')
                        and completed_ms != old[2]):
                    raise ValueError('cloud_photo_completion_clock_changed')
            if self.db.execute('SELECT 1 FROM cloud_photo_tombstones WHERE event_id=?', (event_id,)).fetchone():
                raise ValueError('cloud_photo_event_was_erased')
            self.db.execute('INSERT INTO cloud_photo_retention VALUES(?,?,?,?) ON CONFLICT(event_id) '
                            'DO UPDATE SET revision=excluded.revision,status=excluded.status,completed_ms=excluded.completed_ms',
                            (event_id, revision, status, completed_ms))

    def expire(self, *, now_ms, deletion_ledger=None):
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError('invalid_cloud_photo_expiry_time')
        if self.db.in_transaction:
            raise ValueError('cloud_photo_expiry_requires_own_transaction')
        with self.transaction():
            rows = self.db.execute('SELECT p.key,p.event_id,r.revision FROM cloud_photos p JOIN cloud_photo_retention r ON p.event_id=r.event_id '
                                   "WHERE r.status IN ('resolved','false_positive') AND r.completed_ms<=? ORDER BY p.event_id,p.side LIMIT 300",
                                   (now_ms - 90 * DAY,)).fetchall()
            if rows:
                if deletion_ledger is None or deletion_ledger.db is self.db:
                    raise ValueError('independent_cloud_deletion_ledger_required')
                intents = {row[1]: row[2] for row in rows}
                deletion_ledger.append([{'kind': 'event', 'target': event, 'revision': revision,
                                         'erased_ms': now_ms} for event, revision in intents.items()])
            for row in rows:
                self.db.execute('INSERT INTO cloud_photo_tombstones VALUES(?,?,?)', (row[0], row[1], now_ms))
                self.db.execute('INSERT OR IGNORE INTO cloud_erased_events VALUES(?,?)', (row[1], now_ms))
                self.db.execute('DELETE FROM cloud_photos WHERE key=?', (row[0],))
            return {'erased_photos': len(rows)}
