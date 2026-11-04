"""Explicit resident-confirmed case photo. No camera, recognition or face matching."""
import base64
import hashlib
import io
import re
import sqlite3
import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, field_validator

from edge_hub.resident_threads import session_hash

NAMESPACE = 'resident-case-photo-v1'
DAY = 86_400_000
MAX_PHOTO = 40_000


class Upload(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    session_id: str = Field(pattern='^[a-f0-9]{32}$')
    case_id: str = Field(pattern='^[a-f0-9]{32}$')
    jpeg: str = Field(min_length=4, max_length=53_340)
    consent: Literal[True]
    purpose: Literal['case-followup-v1']

    @field_validator('consent', mode='before')
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError('explicit_resident_confirmation_required')
        return value


def sanitize(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not 0 < len(raw) <= MAX_PHOTO:
            raise ValueError('photo_size')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'JPEG' or not (0 < image.width <= 640 and 0 < image.height <= 640):
                raise ValueError('photo_dimensions')
            image.load()
            clean = ImageOps.exif_transpose(image).convert('RGB')
            output = io.BytesIO()
            clean.save(output, format='JPEG', quality=70, optimize=True)
            value = output.getvalue()
            if len(value) > MAX_PHOTO:
                raise ValueError('photo_size')
            return value
    except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
        raise HTTPException(400, '請重新拍攝清晰的小型相片。') from None


class CasePhotos:
    def __init__(self, services, operations, now=None):
        self.services, self.operations = services, operations
        self.now = now or (lambda: int(time.time() * 1000))

    def live(self, case_id, session=None):
        if not isinstance(case_id, str) or not re.fullmatch('[a-f0-9]{32}', case_id):
            raise HTTPException(404, '未能找到此個案相片。')
        cases, ledger = self.services.cases, self.services.ledger
        head = ledger.checkpoint()
        records = ledger.records(head)
        if any(row['kind'] == 'case' and row['target'] == case_id for row in records):
            raise HTTPException(410, '個案相片已到期或清除。')
        with cases.lock:
            row = cases.db.execute('SELECT status,updated_at_ms,revision FROM service_cases WHERE id=?', (case_id,)).fetchone()
            if row is None:
                raise HTTPException(404, '未能找到此個案相片。')
            has_expiry = cases.db.execute("SELECT 1 FROM sqlite_master WHERE name='case_privacy_expiry'").fetchone()
            if has_expiry and cases.db.execute('SELECT 1 FROM case_privacy_expiry WHERE id=?', (case_id,)).fetchone():
                raise HTTPException(410, '個案相片已到期或清除。')
            if session is not None and not cases.db.execute('SELECT 1 FROM resident_session_cases WHERE session_hash=? AND case_id=?',
                                                           (session_hash(session), case_id)).fetchone():
                raise HTTPException(403, '只能為本輪已交到管理處的個案附相。')
            if row[0] == 'resolved' and row[1] <= self.now() - 90 * DAY:
                raise HTTPException(410, '個案相片已到期或清除。')
            if session is not None and row[0] == 'resolved':
                raise HTTPException(409, '已完成個案不可新增相片。')
            return tuple(row), head

    def put(self, body):
        state = self.live(body.case_id, body.session_id)
        image = sanitize(body.jpeg)
        digest = hashlib.sha256(image).hexdigest()
        ops = self.operations
        with ops.lock:
            if ops.db.in_transaction:
                raise HTTPException(503, '資料正在處理，請稍後再試。')
            old = ops.get(NAMESPACE, body.case_id)
            if old:
                if old['sha256'] != digest:
                    raise HTTPException(409, '此個案已附相片，未重複儲存。')
                return {'stored': True, 'replayed': True, 'case_id': body.case_id}
            used = ops.db.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(payload)),0) FROM cloud_operations WHERE namespace=?', (NAMESPACE,)).fetchone()
            if used[0] >= 300 or used[1] >= 16_000_000:
                raise HTTPException(503, '個案相片空間已滿，文字求助仍可使用。')
            payload = {'jpeg': base64.b64encode(image).decode(), 'consent_at_ms': self.now(),
                       'purpose': 'case-followup-v1', 'method': 'resident-preview-confirm-v1'}
            sealed = ops.seal(NAMESPACE, body.case_id, payload)
            if self.live(body.case_id, body.session_id) != state:
                raise HTTPException(409, '個案剛有更新，請重新確認。')
            ops.put(NAMESPACE, body.case_id, {'sha256': digest, 'sealed': sealed})
        return {'stored': True, 'replayed': False, 'case_id': body.case_id}

    def read(self, case_id):
        state = self.live(case_id)
        record = self.operations.get(NAMESPACE, case_id)
        if not record:
            raise HTTPException(404, '居民未有附上相片。')
        payload = self.operations.open(NAMESPACE, case_id, record['sealed'])
        value = base64.b64decode(payload['jpeg'], validate=True)
        if (not 0 < len(value) <= MAX_PHOTO or hashlib.sha256(value).hexdigest() != record['sha256']
                or payload['method'] != 'resident-preview-confirm-v1' or payload['purpose'] != 'case-followup-v1'):
            raise ValueError('case_photo_integrity')
        if self.live(case_id) != state:
            raise HTTPException(409, '個案剛有更新，請重新查看。')
        return value


def router(services, operations, principal, require_staff):
    routes = APIRouter()
    photos = CasePhotos(services, operations)

    @routes.post('/api/v1/resident/case-photo')
    def upload(body: Upload):
        if getattr(principal(), 'role', None) != 'resident':
            raise HTTPException(403, '請由本輪居民對話確認附相。')
        try:
            return photos.put(body)
        except (OSError, ValueError, KeyError, sqlite3.Error):
            raise HTTPException(503, '未能確認相片已儲存，文字個案仍保留。') from None

    @routes.get('/api/v1/service-desk/requests/{case_id}/photo')
    def read(case_id: str):
        require_staff()
        try:
            data = photos.read(case_id)
        except (OSError, ValueError, KeyError, sqlite3.Error):
            raise HTTPException(503, '暫時未能核對個案相片。') from None
        return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    return routes
