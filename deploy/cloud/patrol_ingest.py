"""Scoped, idempotent site evidence ingestion; no robot control or resident access.

Photo/event/case databases are separate. Every effect is independently replayable;
the receipt is final only after all three photos, event and numbered case exist.
No photo bytes or free text remain in the receipt.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from deploy.cloud.photo_store import validate_image
from deploy.cloud.staff_api import CloudFollowup
from edge_hub.events import Event

INGEST = '/api/v1/patrol/delivery'
PAIR = '/api/v1/service-desk/patrol-site'
SID = re.compile(r'[a-f0-9]{32}')
RECEIPT = re.compile(re.escape(INGEST) + r'/([a-f0-9]{32})')


class PatrolIngest:
    def __init__(self, services, operations):
        self.services, self.ops = services, operations
        self.followup = CloudFollowup(services)
        self.lock = threading.Lock()
        self.inflight = 0  # Accessed only on the ASGI event loop, before any await.

    def pair(self):
        # Existing site identity is stable. Rotation is an explicit revoke/new pair.
        if any(item['active'] for _, item in self.ops.items('patrol-site')):
            raise ValueError('site_already_paired')
        site, token = secrets.token_hex(16), secrets.token_urlsafe(32)
        self.ops.put('patrol-site', site, {'digest': hashlib.sha256(token.encode()).hexdigest(), 'active': True})
        return {'site': site, 'token': token, 'scope': 'patrol_delivery_only'}

    def identity(self, token):
        if not isinstance(token, str) or not 32 <= len(token) <= 128:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        for site, item in self.ops.items('patrol-site'):
            if item['active'] and hmac.compare_digest(digest, item['digest']):
                return site
        return None

    def accept(self, site, payload):
        if not isinstance(payload, dict) or set(payload) != {'event', 'images'}:
            raise ValueError('invalid_delivery')
        event = Event.model_validate(payload['event'])
        if (not SID.fullmatch(event.id) or event.status != 'pending' or event.details.get('is_test')
                or event.type not in ('litter_detected', 'leak_detected', 'smoke_fire_candidate',
                                      'electrical_visual_candidate', 'access_candidate')
                or event.details.get('source') != 'ep_patrol_local' or len(event.zone) > 120
                or len(event.model_dump_json()) > 16000
                or event.at_ms > int(time.time()*1000) + 60000):
            raise ValueError('invalid_candidate')
        images = payload['images']
        if not isinstance(images, dict) or set(images) != {'event', 'left', 'right'}:
            raise ValueError('three_photos_required')
        decoded = {}
        for photo in event.details['photos']:
            value = images[photo['side']]
            if not isinstance(value, str) or len(value) > 470000:
                raise ValueError('invalid_photo')
            data = base64.b64decode(value, validate=True)
            if len(data) > 350000 or hashlib.sha256(data).hexdigest() != photo['sha256']:
                raise ValueError('photo_digest_mismatch')
            validate_image(data, 'JPEG')
            decoded[photo['side']] = data
        identity = site + ':' + event.id
        digest = self.ops.digest(payload['event'])
        with self.lock:
            # Receipt hash has no raw resident/camera information.
            old = self.ops.get('patrol-receipt', identity)
            if old and old['digest'] != digest:
                raise ValueError('delivery_identity_conflict')
            if old and old.get('delivered'):
                return old
            if any(r['kind'] == 'event' and r['target'] == event.id for r in
                   self.services.ledger.records(self.services.ledger.checkpoint())):
                raise ValueError('event_was_erased')
            if not old:
                if self.ops.count('patrol-receipt') >= 20000:
                    raise ValueError('delivery_capacity_reached')
                self.ops.put('patrol-receipt', identity, {'digest': digest, 'delivered': False})
            existing = self.services.events.get_event(event.id)
            if existing and self.ops.digest({**existing.model_dump(), 'status': 'pending'}) != digest:
                raise ValueError('event_identity_conflict')
            now = int(time.time()*1000)
            for photo in event.details['photos']:
                self.services.photos.put(event.id, photo['side'], photo['path'], decoded[photo['side']],
                                         reviewed=True, now_ms=now)
            if not existing:
                self.services.photos.event_state(event.id, 'pending', 1)
                self.services.events.add(event)
            link = self.followup.ensure(existing or event)
            if not link:
                raise ValueError('followup_not_confirmed')
            result = {'digest': digest, 'delivered': True, 'event_id': event.id,
                      'case_number': link['case_number'], 'received_ms': now}
            self.ops.put('patrol-receipt', identity, result)
            return result


def patrol_router(manager, authorize, principal):
    router = APIRouter()

    @router.get(PAIR)
    def status():
        authorize()
        return {'paired': any(v['active'] for _, v in manager.ops.items('patrol-site')),
                'scope': 'patrol_delivery_only', 'robot_control': False}

    @router.post(PAIR)
    def pair():
        authorize()
        try:
            return manager.pair()
        except ValueError:
            raise HTTPException(409, '現場回報已配對，請保留原有憑證。') from None

    @router.delete(PAIR)
    def revoke():
        authorize()
        for site, record in manager.ops.items('patrol-site'):
            if record['active']:
                manager.ops.put('patrol-site', site, {**record, 'active': False})
        return {'revoked': True, 'robot_control_changed': False}

    @router.post(INGEST)
    async def delivery(request: Request):
        identity = principal()
        if identity.role != 'patrol-site':
            raise HTTPException(403)
        if manager.inflight >= 2:
            raise HTTPException(503, '回報通道正忙，現場副本保留稍後重送。')
        manager.inflight += 1
        try:
            raw = bytearray()
            try:
                async with asyncio.timeout(10):
                    async for part in request.stream():
                        raw.extend(part)
                        if len(raw) > 1_450_000:
                            raise HTTPException(413)
            except TimeoutError:
                raise HTTPException(408, '回報傳送逾時；現場副本保留。') from None
            try:
                from edge_hub.event_request import check_event_json_depth
                check_event_json_depth(raw)
                return await run_in_threadpool(manager.accept, identity.subject, json.loads(raw))
            except (ValueError, KeyError, TypeError):
                raise HTTPException(409, '回報內容或相片未通過核對；現場副本保留待核實。') from None
        finally:
            manager.inflight -= 1

    @router.get(INGEST + '/{event_id}')
    def receipt(event_id: str):
        identity = principal()
        if identity.role != 'patrol-site' or not SID.fullmatch(event_id):
            raise HTTPException(403)
        record = manager.ops.get('patrol-receipt', identity.subject + ':' + event_id)
        if not record:
            raise HTTPException(404)
        # Only own delivery/completion receipt; no resident text or control API.
        with manager.services.events._lock:
            row = manager.services.events._connection.execute('SELECT completed_at_ms FROM event_completion WHERE event_id=?', (event_id,)).fetchone()
        return {**record, 'completed_ms': row[0] if row else None}
    return router
