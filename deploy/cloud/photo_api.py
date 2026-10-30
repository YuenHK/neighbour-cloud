"""Read-only staff delivery of existing, bound three-photo patrol evidence.

No local paths, camera, image upload, review mutation or erasure is exposed.
This unpublished adapter requires a completed import and one formal writer;
double checks detect changes but do not make different databases atomic.
"""
import re
import sqlite3
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import Response

from deploy.cloud.photo_store import DAY, MAX_IMAGE

PHOTO_PATH = re.compile(r'/api/v1/patrol/events/[A-Za-z0-9_-]{1,120}/photo')


class PhotoUnavailable(Exception):
    def __init__(self, status):
        self.status = status


class StaffPhotos:
    def __init__(self, services, *, clock=time.monotonic):
        self.services = services
        self.slots = threading.BoundedSemaphore(2)
        self.clock = clock

    def event_snapshot(self, event_id):
        events = self.services.events
        with events._lock:
            if events._connection.in_transaction:
                raise PhotoUnavailable(503)
            row = events._connection.execute('SELECT e.*,c.completed_at_ms FROM events e '
                'LEFT JOIN event_completion c ON c.event_id=e.id WHERE e.id=?', (event_id,)).fetchone()
        if row is None:
            raise PhotoUnavailable(404)
        event = events._from_row(row)
        if event.details.get('source') != 'ep_patrol_local' or not event.evidence:
            raise PhotoUnavailable(404)
        completion = row['completed_at_ms']
        if event.status in ('resolved', 'false_positive'):
            if type(completion) is not int or not 0 <= completion <= int(time.time() * 1000):
                raise PhotoUnavailable(503)
        elif completion is not None:
            raise PhotoUnavailable(503)
        return event, completion, tuple(row)

    def read(self, event_id, side):
        if not self.slots.acquire(blocking=False):
            raise PhotoUnavailable(503)
        deadline = self.clock() + 5

        def budget():
            if self.services.closed or self.clock() >= deadline:
                raise PhotoUnavailable(503)

        try:
            budget()
            ledger = self.services.ledger
            head = ledger.checkpoint()
            records = ledger.records(head)
            budget()
            if any(record['kind'] == 'event' and record['target'] == event_id for record in records):
                raise PhotoUnavailable(410)
            event, completion, fingerprint = self.event_snapshot(event_id)
            selected = next((photo for photo in event.details['photos'] if photo['side'] == side), None)
            if selected is None:
                raise PhotoUnavailable(503)
            photos = self.services.photos
            key = selected['path']
            budget()
            # One read transaction for binding, retention, tombstones and bytes.
            # Never join/commit an outside writer's unfinished transaction.
            with photos.lock:
                if photos.db.in_transaction:
                    raise PhotoUnavailable(503)
                with photos.db:
                    photos.db.execute('BEGIN')
                    if (photos.db.execute('SELECT 1 FROM cloud_erased_events WHERE event_id=?', (event_id,)).fetchone()
                            or photos.db.execute('SELECT 1 FROM cloud_photo_tombstones WHERE event_id=? OR key=?',
                                                 (event_id, key)).fetchone()):
                        raise PhotoUnavailable(410)
                    state = photos.db.execute('SELECT revision,status,completed_ms FROM cloud_photo_retention '
                                              'WHERE event_id=?', (event_id,)).fetchone()
                    if (state is None or type(state[0]) is not int or state[0] < 1
                            or state[1] != event.status or state[2] != completion):
                        raise PhotoUnavailable(503)
                    if completion is not None and completion <= int(time.time() * 1000) - 90 * DAY:
                        raise PhotoUnavailable(410)
                    row = photos.db.execute('SELECT event_id,side,digest,LENGTH(content) FROM cloud_photos '
                                            'WHERE key=?', (key,)).fetchone()
                    if row is None:
                        raise PhotoUnavailable(404)
                    if (tuple(row[:3]) != (event_id, side, selected['sha256'])
                            or type(row[3]) is not int or not 0 < row[3] <= MAX_IMAGE):
                        raise PhotoUnavailable(503)
                    data = photos.get(key)  # Digest and JPEG validation, not a path supplied by the browser.
            budget()
            if self.event_snapshot(event_id)[2] != fingerprint or ledger.checkpoint() != head:
                raise PhotoUnavailable(409)
            if completion is not None and completion <= int(time.time() * 1000) - 90 * DAY:
                raise PhotoUnavailable(410)
            budget()
            return data
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            raise PhotoUnavailable(503) from None
        finally:
            self.slots.release()


def photo_router(services, authorize):
    router = APIRouter()
    reader = StaffPhotos(services)

    @router.get('/api/v1/patrol/events/{event_id}/photo')
    def photo(request: Request, event_id: str = Path(pattern=r'^[A-Za-z0-9_-]{1,120}$'),
              side: Literal['event', 'left', 'right'] = Query(default='event')):
        authorize()
        query = list(request.query_params.multi_items())
        if len(query) > 1 or any(key != 'side' for key, _ in query):
            raise HTTPException(400, '請選擇回報相片。')
        try:
            data = reader.read(event_id, side)
        except PhotoUnavailable as error:
            messages = {404: '未能找到這張回報相片。', 409: '回報資料剛有變更，請重新查看。',
                        410: '這張回報相片已到期或已清除。', 503: '暫時未能核對回報相片，請稍後再試。'}
            raise HTTPException(error.status, messages[error.status]) from None
        return Response(data, media_type='image/jpeg', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    return router
