"""Staff-only event/follow-up adapters; no hardware or native app imports."""
import re
import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from deploy.cloud.photo_api import PhotoUnavailable, StaffPhotos
from edge_hub.patrol_followup import PatrolFollowup

EVENT_ID = r'^[A-Za-z0-9_-]{1,120}$'
PATCH_PATH = re.compile(r'/api/v1/events/[A-Za-z0-9_-]{1,120}')
FOLLOWUP_PATH = re.compile(r'/api/v1/patrol/events/[a-f0-9]{32}/followup')
STAFF_READ_PATHS = {'/api/v1/events', '/api/v1/event-stats', '/api/v1/patrol/followups'}


def staff_path(path):
    return path in STAFF_READ_PATHS or PATCH_PATH.fullmatch(path) or FOLLOWUP_PATH.fullmatch(path)


class EventReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['pending', 'confirmed', 'false_positive', 'resolved']
    expected_revision: int | None = Field(default=None, ge=1, strict=True)


class CloudFollowup(PatrolFollowup):
    def __init__(self, services):
        super().__init__(services.events, services.cases)
        self.services = services
        self.photos = StaffPhotos(services)
        self.ledger = services.ledger

    def flush_case(self, case_id):
        # Event, photo-retention and case stores are separate databases. Keep
        # the existing durable outbox pending until BOTH mirrors acknowledge.
        # A retry reads the mirrors first; it does not move completion clocks.
        with self.cases.lock:
            link = self.cases.db.execute('SELECT * FROM patrol_case_links WHERE case_id=? AND sync_pending=1',
                                         (case_id,)).fetchone()
            if link is None:
                return
            try:
                records = self.ledger.records(self.ledger.checkpoint())
                if any(row['kind'] == 'event' and row['target'] == link['event_id'] for row in records):
                    return  # An outstanding signed erasure must not be revived.
                event = self.events.get_event(link['event_id'])
                if event is None or event.details.get('source') != 'ep_patrol_local':
                    return
                if event.status != link['desired_status']:
                    self.events.update_status(link['event_id'], link['desired_status'])
                event, completion, _ = self.photos.event_snapshot(link['event_id'])
                photos = self.services.photos
                with photos.transaction():
                    old = photos.db.execute('SELECT revision,status,completed_ms FROM cloud_photo_retention '
                                            'WHERE event_id=?', (event.id,)).fetchone()
                    if old is None or type(old[0]) is not int or not 1 <= old[0] < 2**63 - 1:
                        return
                    if (old[1], old[2]) != (event.status, completion):
                        photos.event_state(event.id, event.status, old[0] + 1, completed_ms=completion)
                with self.cases.db:
                    self.cases.db.execute('UPDATE patrol_case_links SET sync_pending=0 WHERE case_id=?', (case_id,))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error, PhotoUnavailable):
                return  # Preserve the committed progress and unfinished outbox.

    def ensure(self, event):
        with self.cases.lock:
            linked = self._link(event.id)
            if linked or event.status in ('resolved', 'false_positive'):
                return linked
            # The native disk-photo check is replaced by the imported database
            # binding + signed deletion ledger checks, never simply skipped.
            try:
                head = self.ledger.checkpoint()
                for side in ('event', 'left', 'right'):
                    self.photos.read(event.id, side)
                current = self.events.get_event(event.id)
                if (current is None or current.model_dump() != event.model_dump()
                        or self.ledger.checkpoint() != head):
                    raise HTTPException(409, '回報剛有變更，請重新查看後再處理。')
            except PhotoUnavailable as error:
                raise HTTPException(error.status, '三張現場相片未能核對，未建立新個案。') from None
            return super().ensure(event)


def staff_router(services, authorize):
    router = APIRouter()
    manager = CloudFollowup(services)

    @router.get('/api/v1/events')
    def events(limit: int = Query(default=100, ge=1, le=100),
               offset: int = Query(default=0, ge=0, le=1_000_000)):
        authorize()
        return services.events.query(limit=limit, offset=offset)

    @router.get('/api/v1/event-stats')
    def stats():
        authorize()
        return services.events.stats()

    @router.get('/api/v1/patrol/followups')
    def followups(ids: str = Query(default='', max_length=3300, pattern='^[a-f0-9,]*$')):
        authorize()
        selected = ids.split(',') if ids else None
        if selected and (len(selected) > 100 or any(not re.fullmatch('[a-f0-9]{32}', item) for item in selected)):
            raise HTTPException(422, '請選擇有效回報。')
        return {'items': manager.snapshot(selected)}

    @router.post('/api/v1/patrol/events/{event_id}/followup')
    def ensure(event_id: str = Path(pattern='^[a-f0-9]{32}$')):
        authorize()
        event = services.events.get_event(event_id)
        if event is None or event.details.get('source') != 'ep_patrol_local' or event.details.get('is_test') is True:
            raise HTTPException(404, '未能找到這項巡查回報。')
        try:
            result = manager.ensure(event)
        except ValueError:
            raise HTTPException(409, '回報未能核對，未建立新個案。') from None
        if result is None:
            raise HTTPException(410, '已結束的回報不會重新建立個案。')
        return result

    @router.patch('/api/v1/events/{event_id}')
    def review(update: EventReview, event_id: str = Path(pattern=EVENT_ID)):
        authorize()
        event = services.events.get_event(event_id)
        if event is None:
            raise HTTPException(404, '未能找到這項回報。')
        if event.details.get('source') == 'ep_patrol_local' and event.details.get('is_test') is not True:
            return manager.review_event(event, update.status, update.expected_revision)
        return services.events.update_status(event_id, update.status)

    return router
