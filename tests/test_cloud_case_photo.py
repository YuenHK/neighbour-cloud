import base64
import io
import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from deploy.cloud.case_photo import NAMESPACE, CasePhotos, Upload, router
from deploy.cloud.operations import Operations, migrate
from deploy.cloud.retention_restore import reconcile
from edge_hub.resident_threads import session_hash

CASE = 'a' * 32
SESSION = 'b' * 32


@pytest.fixture
def prepared():
    db = sqlite3.connect(':memory:', check_same_thread=False)
    db.execute('CREATE TABLE service_cases(id TEXT PRIMARY KEY,status TEXT,updated_at_ms INTEGER,revision INTEGER)')
    db.execute('INSERT INTO service_cases VALUES(?,?,?,1)', (CASE, 'new', 1))
    db.execute('CREATE TABLE resident_session_cases(session_hash TEXT,case_id TEXT)')
    db.execute('INSERT INTO resident_session_cases VALUES(?,?)', (session_hash(SESSION), CASE))
    db.commit()
    estate = sqlite3.connect(':memory:', check_same_thread=False)
    migrate(estate)
    ops = Operations(estate, b'synthetic-key-never-production-12')
    records = []
    ledger = SimpleNamespace(checkpoint=lambda: {'seq': len(records)}, records=lambda _: records)
    services = SimpleNamespace(cases=SimpleNamespace(db=db, lock=threading.RLock()), ledger=ledger)
    image = io.BytesIO()
    Image.new('RGB', (160, 120), '#e3b48a').save(image, 'JPEG')
    body = Upload(session_id=SESSION, case_id=CASE, jpeg=base64.b64encode(image.getvalue()).decode(), consent=True, purpose='case-followup-v1')
    yield services, ops, records, body
    db.close()
    estate.close()


def test_explicit_consent_session_binding_encryption_and_retry(prepared):
    services, ops, _, body = prepared
    photos = CasePhotos(services, ops)
    with pytest.raises(HTTPException) as error:
        photos.put(body.model_copy(update={'session_id': 'c' * 32}))
    assert error.value.status_code == 403
    assert photos.put(body)['replayed'] is False
    assert photos.put(body)['replayed'] is True
    assert ops.count(NAMESPACE) == 1
    record = ops.get(NAMESPACE, CASE)
    assert body.jpeg not in json.dumps(record)
    clean = photos.read(CASE)
    with Image.open(io.BytesIO(clean)) as image:
        assert not image.getexif() and image.size == (160, 120)


def test_auth_no_public_image_no_false_consent(prepared):
    services, ops, _, body = prepared
    actor = SimpleNamespace(role='resident')
    def staff():
        if actor.role != 'staff':
            raise HTTPException(403)
    app = FastAPI()
    app.include_router(router(services, ops, lambda: actor, staff))
    client = TestClient(app)
    payload = body.model_dump()
    assert client.post('/api/v1/resident/case-photo', json={**payload, 'consent': False}).status_code == 422
    assert client.post('/api/v1/resident/case-photo', json={**payload, 'consent': 1}).status_code == 422
    assert client.get(f'/api/v1/service-desk/requests/{CASE}/photo').status_code == 403
    assert client.post('/api/v1/resident/case-photo', json=payload).status_code == 200
    actor.role = 'staff'
    response = client.get(f'/api/v1/service-desk/requests/{CASE}/photo')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert client.post('/api/v1/resident/case-photo', json=payload).status_code == 403


def test_expiry_ledger_and_estate_backup_scrub_only_this_case_namespace(prepared):
    services, ops, records, body = prepared
    photos = CasePhotos(services, ops, now=lambda: 100 * 86_400_000)
    photos.put(body)
    ops.put('vroid-library', CASE, {'preserve': True})
    records.append({'kind': 'case', 'target': CASE, 'erased_ms': 123, 'revision': 1})
    with pytest.raises(HTTPException) as error:
        photos.read(CASE)
    assert error.value.status_code == 410
    with ops.db:
        assert reconcile(ops.db, 'estate', records) == 1
    assert ops.get(NAMESPACE, CASE) is None
    assert ops.get('vroid-library', CASE) == {'preserve': True}
    with sqlite3.connect(':memory:') as legacy:
        assert reconcile(legacy, 'estate', records) == 0


def test_malformed_image_and_completed_case_do_not_save(prepared):
    services, ops, _, body = prepared
    photos = CasePhotos(services, ops, now=lambda: 1000)
    with pytest.raises(HTTPException):
        photos.put(body.model_copy(update={'jpeg': base64.b64encode(b'not an image').decode()}))
    services.cases.db.execute("UPDATE service_cases SET status='resolved'")
    services.cases.db.commit()
    with pytest.raises(HTTPException) as error:
        photos.put(body)
    assert error.value.status_code == 409 and ops.count(NAMESPACE) == 0
