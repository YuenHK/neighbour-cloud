import base64
import hashlib
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from edge_hub.photo_privacy import ApprovedPhoto, MaskApproval, PhotoPrivacy, privacy_photo_router


def image():
    ok, jpg = cv2.imencode('.jpg', np.full((360, 640, 3), 220, np.uint8))
    assert ok
    return jpg.tobytes()


def approval(preview):
    return MaskApproval(token=preview['token'], preview_sha256=preview['preview_sha256'], confirmed=True)


def test_only_exact_preview_is_approved_original_is_unchanged(tmp_path):
    privacy = PhotoPrivacy(tmp_path, detector=SimpleNamespace(detect=lambda img: [(5,5,80,90)]))
    original = image()
    preview = privacy.prepare(original, 'event', [[200,100,100,80]])
    expected = base64.b64decode(preview['jpeg'])
    decoded = cv2.imdecode(np.frombuffer(expected, np.uint8), cv2.IMREAD_COLOR)
    assert decoded[30,30].max() < 5 and decoded[130,230].max() < 5
    assert decoded[300,500].min() > 200
    photo = privacy.approve(approval(preview), 'event', hashlib.sha256(original).hexdigest())
    assert photo.jpeg == expected and original == image()
    with pytest.raises(ValueError):
        privacy.approve(approval(preview), 'event', photo.source_sha256)


def test_changed_source_or_preview_cannot_be_approved(tmp_path, monkeypatch):
    privacy = PhotoPrivacy(tmp_path, detector=SimpleNamespace(detect=lambda img: []))
    preview = privacy.prepare(image(), 'event', [])
    with pytest.raises(ValueError):
        privacy.approve(approval(preview), 'other', hashlib.sha256(image()).hexdigest())
    with pytest.raises(ValueError):
        privacy.approve(approval(preview), 'event', 'f'*64)
    changed = approval(preview).model_copy(update={'preview_sha256': 'f'*64})
    with pytest.raises(ValueError):
        privacy.approve(changed, 'event', hashlib.sha256(image()).hexdigest())
    privacy.prepare(image(), 'event', [[0,0,640,360]])
    with pytest.raises(ValueError):
        privacy.approve(approval(preview), 'event', hashlib.sha256(image()).hexdigest())


def test_detector_failure_or_invalid_box_never_creates_approval(tmp_path):
    privacy = PhotoPrivacy(tmp_path, detector=SimpleNamespace(detect=lambda img: (_ for _ in ()).throw(ValueError())))
    with pytest.raises(ValueError):
        privacy.prepare(image(), 'event', [])
    assert not privacy.pending
    for box in ([True,0,1,1], [-1,0,2,2], [0,0,641,360], [0,0,0,1]):
        with pytest.raises(ValueError):
            privacy.prepare(image(), 'event', [box])
    assert not privacy.pending


def test_http_approval_requires_operator_same_origin_and_exact_single_use_preview(tmp_path, monkeypatch):
    from edge_hub import patrol_cloud, photo_privacy
    raw = image()
    target = tmp_path/'events/ep-patrol/event.jpg'
    target.parent.mkdir(parents=True)
    target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    event = SimpleNamespace(details={'source': 'ep_patrol_local', 'photo_sha256': digest, 'finding': 'litter',
                            'photos': [{'side': 'event', 'path': 'events/ep-patrol/event.jpg', 'sha256': digest}]})
    manager = SimpleNamespace(data_root=tmp_path, store=SimpleNamespace(get_event=lambda _: event))
    monkeypatch.setattr(photo_privacy, 'PersonPrivacyDetector', lambda _: SimpleNamespace(detect=lambda img: [(0,0,40,40)]))
    sent = []
    def review(photo, candidates):
        assert isinstance(photo, ApprovedPhoto)
        sent.append(photo.jpeg)
        return candidates, 'reviewed'
    monkeypatch.setattr(patrol_cloud, 'review', review)
    def authorize(key):
        if key != 'synthetic':
            raise HTTPException(403)
    app = FastAPI()
    app.include_router(privacy_photo_router(manager, authorize, tmp_path))
    with TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1',1)) as client:
        url = '/api/v1/patrol/events/example/'
        headers = {'X-Operator-Key': 'synthetic'}
        assert client.post(url+'privacy-preview', json={'boxes': []}).status_code == 403
        assert client.post(url+'privacy-preview', json={'boxes': []}, headers={**headers, 'Origin': 'https://outside.invalid'}).status_code == 403
        result = client.post(url+'privacy-preview', json={'boxes': [[100,100,20,20]]}, headers=headers).json()
        assert not sent
        body = {key: result[key] for key in ('token','preview_sha256')}
        assert client.post(url+'privacy-approve', json={**body,'confirmed':False}, headers=headers).status_code == 409
        assert client.post(url+'privacy-approve', json={**body,'confirmed':True}, headers=headers).status_code == 200
        assert sent == [base64.b64decode(result['jpeg'])] and sent[0] != raw
        assert client.post(url+'privacy-approve', json={**body,'confirmed':True}, headers=headers).status_code == 409
        assert len(sent) == 1
