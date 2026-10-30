"""Local masking preview and single-use approval for one existing EP event photo.

Automatic detection is best effort. Every upload requires the operator to inspect
the exact final image; camera access, gimbal and robot control are never used.
"""
import base64
import hashlib
import secrets
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from edge_hub.approved_photo import ApprovedPhoto
from edge_hub.privacy import PersonPrivacyDetector
from edge_hub.service_desk import local_resident_request


class MaskPreview(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    boxes: list[list[int]] = Field(default_factory=list, max_length=64)


class MaskApproval(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    token: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    preview_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirmed: bool


class PhotoPrivacy:
    def __init__(self, project_root, *, detector=None):
        self.root, self.detector = Path(project_root), detector
        self.lock = threading.RLock()
        self.pending = {}

    def prepare(self, jpeg, event_id, boxes):
        if not isinstance(jpeg, bytes) or len(jpeg) > 350000:
            raise ValueError('invalid_photo')
        image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape != (360, 640, 3):
            raise ValueError('invalid_photo')
        manual = []
        for box in boxes:
            if (len(box) != 4 or any(type(v) is not int for v in box)
                    or not 0 <= box[0] < 640 or not 0 <= box[1] < 360
                    or not 0 < box[2] <= 640-box[0] or not 0 < box[3] <= 360-box[1]):
                raise ValueError('invalid_mask')
            manual.append(tuple(box))
        with self.lock:
            if self.detector is None:
                self.detector = PersonPrivacyDetector(self.root/'models/person-yolox-tiny.onnx')
            automatic = self.detector.detect(image)
            masked = image.copy()
            # Opaque rectangles rather than reversible weak blur.
            for x, y, w, h in [*automatic, *manual]:
                if (any(type(v) not in (int, np.int32, np.int64) for v in (x,y,w,h))
                        or x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > 640 or y+h > 360):
                    raise ValueError('invalid_detector_geometry')
                masked[y:y+h, x:x+w] = 0
            ok, encoded = cv2.imencode('.jpg', masked, [cv2.IMWRITE_JPEG_QUALITY, 88])
            if not ok:
                raise ValueError('mask_encode_failed')
            photo = ApprovedPhoto(encoded.tobytes(), hashlib.sha256(jpeg).hexdigest(),
                                  hashlib.sha256(encoded.tobytes()).hexdigest())
            now = time.monotonic()
            self.pending = {key: value for key, value in self.pending.items() if value[0] > now}
            # A new preview invalidates earlier approvals for the same event.
            self.pending = {key: value for key, value in self.pending.items() if value[1] != event_id}
            if len(self.pending) >= 8:
                raise ValueError('preview_busy')
            token = secrets.token_urlsafe(32)
            self.pending[token] = (now+300, event_id, photo)
        return {'token': token, 'preview_sha256': photo.preview_sha256,
                'jpeg': base64.b64encode(photo.jpeg).decode(), 'automatic_masks': len(automatic),
                'manual_masks': len(manual), 'expires_in_seconds': 300,
                'notice': '請檢查全張相，拖曳補遮人臉、車牌、門牌或其他私隱，再更新預覽。自動遮蓋可能遺漏；未確認不會上傳。'}

    def approve(self, body, event_id, source_hash):
        with self.lock:
            entry = self.pending.get(body.token)
            if (body.confirmed is not True or entry is None or entry[0] <= time.monotonic()
                    or entry[1] != event_id or entry[2].preview_sha256 != body.preview_sha256
                    or entry[2].source_sha256 != source_hash):
                raise ValueError('preview_expired_or_changed')
            self.pending.pop(body.token)  # Never replay a cloud request with this approval.
            return entry[2]


def privacy_photo_router(manager, authorize, project_root):
    router = APIRouter()
    previews = PhotoPrivacy(project_root)

    def source(event_id):
        event = manager.store.get_event(event_id)
        if not event or event.details.get('source') != 'ep_patrol_local':
            raise HTTPException(404)
        central = next((p for p in event.details.get('photos', []) if p.get('side') == 'event'), None)
        if central is None:
            raise HTTPException(404)
        path = (manager.data_root/central['path']).resolve()
        root = (manager.data_root/'events/ep-patrol').resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 350000:
            raise HTTPException(404)
        jpeg = path.read_bytes()
        digest = hashlib.sha256(jpeg).hexdigest()
        if digest != central['sha256'] or digest != event.details['photo_sha256']:
            raise HTTPException(409, '原相片已改變，未有上傳。')
        return event, jpeg, digest

    def check(request, key):
        authorize(key)
        if not local_resident_request(request):
            raise HTTPException(403)

    @router.post('/api/v1/patrol/events/{event_id}/privacy-preview')
    def preview(event_id: str, body: MaskPreview, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        _, jpeg, _ = source(event_id)
        try:
            result = previews.prepare(jpeg, event_id, body.boxes)
        except (ValueError, OSError, RuntimeError, cv2.error):
            raise HTTPException(409, '遮蓋預覽未完成，沒有上傳相片；請先在本機核實。') from None
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @router.post('/api/v1/patrol/events/{event_id}/privacy-approve')
    def approve(event_id: str, body: MaskApproval, request: Request, x_operator_key: str | None = Header(default=None)):
        check(request, x_operator_key)
        event, _, digest = source(event_id)
        try:
            approved = previews.approve(body, event_id, digest)
        except ValueError:
            raise HTTPException(409, '預覽已過期或改變，請重新檢查；沒有上傳。') from None
        from edge_hub.patrol_cloud import review
        kind = event.details.get('finding')
        if kind not in {'litter', 'standing_water', 'smoke_flame', 'restricted_presence'}:
            raise HTTPException(409)
        findings, status = review(approved, {kind})
        return JSONResponse({'status': status, 'findings': sorted(findings) if status == 'reviewed' else [],
                             'source_sha256': digest, 'preview_sha256': approved.preview_sha256,
                             'review_required': True}, headers={'Cache-Control': 'no-store'})
    return router
