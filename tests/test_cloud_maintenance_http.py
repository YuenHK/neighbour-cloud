import asyncio
import sqlite3
import threading
import time

import httpx
import pytest
import test_cloud_bootstrap
import test_cloud_google_identity
from fastapi.testclient import TestClient

from deploy.cloud.bootstrap import open_services
from deploy.cloud.google_identity import GoogleIdentityVerifier
from deploy.cloud.http_app import create_app
from deploy.cloud.maintenance import CloudMaintenance

prepared = test_cloud_bootstrap.prepared
seeded = test_cloud_bootstrap.seeded
keys = test_cloud_google_identity.keys
ORIGIN = 'https://neighbour.example'


def test_formal_lifespan_blocks_until_maintenance_drains_but_staff_can_read_cached_status(seeded, keys, tmp_path, monkeypatch):
    profile = seeded[0]
    services = open_services(profile, signing_key_loader=lambda: test_cloud_bootstrap.KEY)
    job = CloudMaintenance(services, profile, lambda: sqlite3.connect(tmp_path / 'unused-backup'),
                           test_cloud_bootstrap.KEY, scratch_root=tmp_path)
    started, release = threading.Event(), threading.Event()

    def controlled_run(fence):
        assert fence()
        started.set()
        assert release.wait(5)
        job.state.update(last_success=True, last_error=None)

    monkeypatch.setattr(job, 'run_once', controlled_run)

    def jwks(_request):
        return httpx.Response(200, json={'keys': [keys[1]]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(jwks))
    verifier = GoogleIdentityVerifier(test_cloud_google_identity.CLIENT,
        {'staff-subject': 'staff', 'resident-subject': 'resident'}, client=client)
    staff = {'Authorization': 'Bearer ' + test_cloud_google_identity.token(keys), 'Origin': ORIGIN}
    resident = {'Authorization': 'Bearer ' + test_cloud_google_identity.token(keys, sub='resident-subject'), 'Origin': ORIGIN}
    try:
        with pytest.raises(ValueError, match='matching_formal'):
            create_app(services, verifier, origin=ORIGIN, maintenance=job, storage_acceptance=True)
        app = create_app(services, verifier, origin=ORIGIN, maintenance=job)
        with TestClient(app, base_url=ORIGIN) as browser:
            assert started.wait(3)
            assert browser.get('/health').json()['public_ready'] is False
            assert browser.get('/api/v1/resident/session', headers=resident).status_code == 503
            assert browser.get('/api/v1/service-desk/requests', headers=staff).status_code == 503
            assert browser.get('/api/v1/governance/retention').status_code == 401
            assert browser.get('/api/v1/governance/retention', headers=resident).status_code == 403
            before = services.journal.recent()
            status = browser.get('/api/v1/governance/retention', headers=staff)
            assert status.status_code == 200 and status.json()['automatic_deletion_enabled'] is True
            assert services.journal.recent() == before  # No new SQL writer inside the backup barrier.
            assert browser.get('/api/v1/governance/audit', headers=staff).status_code == 503
            release.set()
            for _ in range(100):
                if browser.get('/health').json()['public_ready']:
                    break
                time.sleep(.01)
            assert browser.get('/health').json()['public_ready'] is True
            session = browser.get('/api/v1/resident/session', headers=resident)
            assert session.status_code == 200 and session.json()['governance_supported'] is True
            assert browser.get('/api/v1/service-desk/requests', headers=staff).status_code == 200
            assert browser.get('/api/v1/governance/audit?limit=20', headers=staff).status_code == 200
            assert browser.get('/api/v1/governance/audit?limit=999', headers=staff).status_code == 422
            assert browser.get('/api/v1/governance/audit', headers=resident).status_code == 403
        assert job.gate.stopping and job.scheduled is False and services.closed
        assert not (tmp_path / 'unused-backup').exists()
    finally:
        release.set()
        services.close()
        asyncio.run(client.aclose())
