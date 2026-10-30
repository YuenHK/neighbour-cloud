from __future__ import annotations

import json
import logging
import re
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

EventStatus = Literal["pending", "confirmed", "false_positive", "resolved"]
EXPORT_SNAPSHOT_LIMIT = 2


def _sqlite_int(value, *, minimum=0, maximum=2**63 - 1):
    return type(value) is int and minimum <= value <= maximum


class EventStreamMismatch(ValueError):
    pass


class EventExportBusy(RuntimeError):
    pass


class Event(BaseModel):
    id: str
    type: Literal["litter_detected", "leak_detected", "temperature_drill", "robot_fault", "smoke_fire_candidate", "access_candidate", "electrical_visual_candidate"]
    zone: str
    at_ms: int
    severity: Literal["notice", "warning", "critical"]
    evidence: str | None = None
    details: dict = Field(default_factory=dict)
    status: EventStatus = "pending"

    @field_validator("evidence")
    @classmethod
    def evidence_must_be_privacy_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.replace("\\", "/").lower()
        if re.fullmatch(r'events/ep-patrol/[a-f0-9]{32}\.jpg', value):
            return value
        if (
            not normalized.startswith("events/")
            or "/../" in f"/{normalized}/"
            or not normalized.endswith(("-blurred.jpg", "-blurred.jpeg", "-blurred.png"))
        ):
            raise ValueError("evidence must be a relative blurred event image path")
        return value

    @model_validator(mode='after')
    def private_patrol_snapshot(self):
        if (self.evidence and self.evidence.startswith('events/ep-patrol/')
                and (self.details.get('source') != 'ep_patrol_local' or self.details.get('review_required') is not True
                    or not re.fullmatch('[a-f0-9]{64}', str(self.details.get('photo_sha256', '')))
                    or not self.details.get('robot_sn') or not self.details.get('frame_key'))):
            raise ValueError('private EP snapshots require bound source metadata and staff review')
        if self.evidence and self.evidence.startswith('events/ep-patrol/'):
            photos = self.details.get('photos')
            if (not isinstance(photos, list) or len(photos) != 3
                    or any(not isinstance(photo, dict) for photo in photos)
                    or {photo.get('side') for photo in photos} != {'event', 'left', 'right'}
                    or len({photo.get('frame_key') for photo in photos}) != 3
                    or any(not re.fullmatch(r'events/ep-patrol/[a-f0-9]{32}\.jpg', str(photo.get('path', '')))
                           or not re.fullmatch('[a-f0-9]{64}', str(photo.get('sha256', '')))
                           for photo in photos)):
                raise ValueError('three distinct bound event/left/right photos required')
            central = next(photo for photo in photos if photo['side'] == 'event')
            if central['path'] != self.evidence or central['sha256'] != self.details['photo_sha256']:
                raise ValueError('central photo must match event evidence')
        return self


class EventStore:
    def __init__(self, database: str | Path = ":memory:", *, connection_factory=None,
                 export_snapshot_factory=None, initialize=True) -> None:
        if type(initialize) is not bool or (not initialize and connection_factory is None):
            raise ValueError('explicit_existing_event_store_required')
        if export_snapshot_factory is not None and not callable(export_snapshot_factory):
            raise ValueError('explicit_event_export_snapshot_factory_required')
        self._export_snapshot_factory = export_snapshot_factory
        if database != ":memory:":
            path = Path(database)
            path.parent.mkdir(parents=True, exist_ok=True)
            database = path
        connect = sqlite3.connect if connection_factory is None else connection_factory
        self._connection = connect(str(database), check_same_thread=False)
        try:
            self._connection.row_factory = sqlite3.Row
            self._lock = threading.Lock()
            self._export_slots = threading.BoundedSemaphore(EXPORT_SNAPSHOT_LIMIT)
            self._export_metrics_lock = threading.Lock()
            self._export_metrics = {'active': 0, 'prepared_total': 0, 'rejected_total': 0, 'failed_total': 0}
            self._listeners: list[Callable[[Event], None]] = []
            if initialize:
                self._initialize_schema()
            else:
                rows = self._connection.execute('SELECT id,stream_id FROM event_stream_metadata').fetchall()
                if (len(rows) != 1 or rows[0]['id'] != 1 or not isinstance(rows[0]['stream_id'], str)
                        or not re.fullmatch('[0-9a-f]{32}', rows[0]['stream_id'])):
                    raise ValueError('existing_event_stream_identity_required')
                self._stream_id = rows[0]['stream_id']
        except BaseException:
            # Failed construction has no usable owner to call close(). Closing
            # also rolls back uncommitted migration writes and releases locks.
            self._connection.close()
            raise

    def _initialize_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                zone TEXT NOT NULL,
                at_ms INTEGER NOT NULL,
                severity TEXT NOT NULL,
                evidence TEXT,
                details_json TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        self._connection.commit()
        self._connection.execute('CREATE TABLE IF NOT EXISTS event_stream_metadata '
                                 '(id INTEGER PRIMARY KEY CHECK(id=1), stream_id TEXT NOT NULL)')
        self._connection.execute('INSERT OR IGNORE INTO event_stream_metadata VALUES (1,?)',
                                 (uuid4().hex,))
        rows = self._connection.execute('SELECT id,stream_id FROM event_stream_metadata').fetchall()
        if (len(rows) != 1 or rows[0]['id'] != 1 or not isinstance(rows[0]['stream_id'], str)
                or not re.fullmatch('[0-9a-f]{32}', rows[0]['stream_id'])):
            raise ValueError('invalid persisted event stream identity; do not regenerate silently')
        self._stream_id = rows[0]['stream_id']
        self._connection.commit()
        self._connection.execute('CREATE TABLE IF NOT EXISTS event_ingest_sequence '
                                 '(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE)')
        self._connection.execute('INSERT OR IGNORE INTO event_ingest_sequence(event_id) '
                                 'SELECT id FROM events WHERE NOT EXISTS '
                                 '(SELECT 1 FROM event_ingest_sequence s WHERE s.event_id=events.id) '
                                 'ORDER BY rowid')
        self._connection.execute('CREATE INDEX IF NOT EXISTS events_at_ms_id ON events(at_ms, id)')
        self._connection.commit()
        self._connection.execute('CREATE TABLE IF NOT EXISTS event_completion ('
                                 'event_id TEXT PRIMARY KEY,completed_at_ms INTEGER NOT NULL,observed INTEGER NOT NULL DEFAULT 0)')
        # Old records have no completion timestamp: start a conservative clock
        # when first observed complete, never backdate it to camera time.
        import time
        self._connection.execute("INSERT OR IGNORE INTO event_completion SELECT id,?,1 FROM events WHERE status IN ('resolved','false_positive')",
                                 (int(time.time()*1000),))
        self._connection.commit()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Event:
        return Event(
            id=row["id"],
            type=row["type"],
            zone=row["zone"],
            at_ms=row["at_ms"],
            severity=row["severity"],
            evidence=row["evidence"],
            details=json.loads(row["details_json"]),
            status=row["status"],
        )

    def add(self, event: Event) -> Event:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO events(id, type, zone, at_ms, severity, evidence, details_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.type,
                    event.zone,
                    event.at_ms,
                    event.severity,
                    event.evidence,
                    json.dumps(event.details, ensure_ascii=False),
                    event.status,
                ),
            )
            self._connection.execute('INSERT INTO event_ingest_sequence(event_id) VALUES (?)', (event.id,))
        for listener in tuple(self._listeners):
            try:
                listener(event)
            except Exception:  # noqa: BLE001 -- commit already succeeded; notifications are best effort
                # Never log callback errors, event details, paths or credentials.
                logging.getLogger(__name__).warning('event notification failed; recover through cursor pages')
        return event

    def subscribe(self, listener: Callable[[Event], None]) -> None:
        self._listeners.append(listener)

    def export_metrics(self):
        with self._export_metrics_lock:
            return {**self._export_metrics, 'snapshot_limit': EXPORT_SNAPSHOT_LIMIT,
                    'scope': 'store-instance counters; prepared snapshot is not delivery ACK; resets on recreation'}

    @contextmanager
    def export_snapshot(self):
        """Temporary disk snapshot; release the source lock before streaming to clients."""
        with self._export_metrics_lock:
            if not self._export_slots.acquire(blocking=False):
                self._export_metrics['rejected_total'] += 1
                raise EventExportBusy('event export capacity reached')
            self._export_metrics['active'] += 1
        try:
            factory = self._export_snapshot_factory or self._native_export_snapshot
            with factory() as snapshot:
                with self._export_metrics_lock:
                    self._export_metrics['prepared_total'] += 1
                yield snapshot
        except Exception:  # Count only; never retain error text or source paths, then propagate.
            with self._export_metrics_lock:
                self._export_metrics['failed_total'] += 1
            raise
        finally:
            with self._export_metrics_lock:
                self._export_metrics['active'] -= 1
                self._export_slots.release()

    @contextmanager
    def _native_export_snapshot(self):
        if not callable(getattr(self._connection, 'backup', None)):
            raise sqlite3.NotSupportedError('event export requires an explicit snapshot provider')
        with tempfile.TemporaryDirectory(prefix='zhiwei-event-export-') as directory:
            snapshot = sqlite3.connect(str(Path(directory) / 'snapshot.sqlite3'), check_same_thread=False)
            try:
                snapshot.row_factory = sqlite3.Row
                with self._lock:
                    deadline = time.monotonic() + 5

                    def progress(status, remaining, total):
                        if time.monotonic() >= deadline:
                            raise TimeoutError('event export snapshot budget exceeded')

                    self._connection.backup(snapshot, pages=128, progress=progress, sleep=.01)
                yield snapshot
            finally:
                snapshot.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def all(self) -> list[Event]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM events ORDER BY at_ms DESC").fetchall()
        return [self._from_row(row) for row in rows]

    def get_event(self, event_id):
        with self._lock:
            row = self._connection.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
        return self._from_row(row) if row else None

    def since(self, at_ms: int) -> list[Event]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM events WHERE at_ms >= ? ORDER BY at_ms DESC", (at_ms,)
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def query(self, *, since_ms=None, limit=1000, offset=0):
        if (not _sqlite_int(limit, minimum=1, maximum=1000) or not _sqlite_int(offset)
                or (since_ms is not None and not _sqlite_int(since_ms, minimum=-(2**63)))):
            raise ValueError('invalid event query bounds')
        where, parameters = (' WHERE at_ms >= ?', [since_ms]) if since_ms is not None else ('', [])
        with self._lock:
            rows = self._connection.execute('SELECT * FROM events' + where +
                                            ' ORDER BY at_ms DESC, id DESC LIMIT ? OFFSET ?',
                                            [*parameters, limit, offset]).fetchall()
        return [self._from_row(row) for row in rows]

    def latest_cursor(self):
        with self._lock:
            # MAX(seq) returns NULL after clear(), but AUTOINCREMENT keeps the
            # high-water mark. Report that durable mark even while the table is empty.
            row = self._connection.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='event_ingest_sequence'").fetchone()
        return row[0] if row else 0

    def stream_state(self):
        with self._lock:
            row = self._connection.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='event_ingest_sequence'").fetchone()
            return {'stream_id': self._stream_id, 'cursor': row[0] if row else 0}

    def page(self, *, after=0, limit=100, through=None, expected_stream_id=None):
        if (not _sqlite_int(after) or not _sqlite_int(limit, minimum=1, maximum=500)
                or (through is not None and not _sqlite_int(through))):
            raise ValueError('invalid cursor or page size')
        query = ('SELECT e.*, s.seq AS ingest_seq FROM events e JOIN event_ingest_sequence s '
                 'ON s.event_id=e.id WHERE s.seq > ?')
        parameters = [after]
        if through is not None:
            query += ' AND s.seq <= ?'
            parameters.append(through)
        with self._lock:
            if expected_stream_id is not None and expected_stream_id != self._stream_id:
                raise EventStreamMismatch('event stream identity changed; explicit recovery required')
            if expected_stream_id is not None:
                high = self._connection.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name='event_ingest_sequence'").fetchone()
                if after > (high[0] if high else 0):
                    raise EventStreamMismatch('cursor exceeds stream high water; explicit recovery required')
            rows = self._connection.execute(query + ' ORDER BY s.seq ASC LIMIT ?',
                                            [*parameters, limit + 1]).fetchall()
        selected = rows[:limit]
        result = {'items': [self._from_row(row) for row in selected],
                  'next_cursor': selected[-1]['ingest_seq'] if selected else after,
                  'has_more': len(rows) > limit}
        if expected_stream_id is not None:
            result['stream_id'] = self._stream_id
        return result

    def update_status(self, event_id: str, event_status: EventStatus) -> Event | None:
        if event_status not in ('pending', 'confirmed', 'false_positive', 'resolved'):
            raise ValueError('invalid event status')
        with self._lock, self._connection:
            previous = self._connection.execute('SELECT status FROM events WHERE id=?', (event_id,)).fetchone()
            self._connection.execute(
                "UPDATE events SET status = ? WHERE id = ?", (event_status, event_id)
            )
            row = self._connection.execute(
                "SELECT * FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            # Validate the returned event before committing. A corrupt persisted
            # row must not turn a failed review response into a committed change.
            updated = self._from_row(row) if row else None
            if updated:
                if event_status in ('resolved', 'false_positive'):
                    import time
                    self._connection.execute('INSERT OR IGNORE INTO event_completion VALUES (?,?,0)', (event_id, int(time.time()*1000)))
                elif previous and previous[0] in ('resolved', 'false_positive'):
                    self._connection.execute('DELETE FROM event_completion WHERE event_id=?', (event_id,))
        return updated

    def stats(self) -> dict[str, int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT status, COUNT(*) AS count FROM events GROUP BY status"
            ).fetchall()
        result = {status: 0 for status in ("pending", "confirmed", "false_positive", "resolved")}
        result.update({row["status"]: row["count"] for row in rows})
        result["total"] = sum(result.values())
        return result

    def clear(self) -> int:
        with self._lock, self._connection:
            count = self._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            self._connection.execute("DELETE FROM events")
            # AUTOINCREMENT retains its high-water mark after DELETE, so live
            # consumers do not get stuck after an operator clears the events.
            self._connection.execute('DELETE FROM event_ingest_sequence')
        return int(count)
