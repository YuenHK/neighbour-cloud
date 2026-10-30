import asyncio

import pytest
import test_cloud_bootstrap
from fastapi import HTTPException

from deploy.cloud.google_identity import InvalidIdentity

prepared = test_cloud_bootstrap.prepared
seeded = test_cloud_bootstrap.seeded


def site(clock=None):
    from deploy.cloud.site_access import SiteSessions, password_hash
    return SiteSessions(password_hash('synthetic-manager', rounds=100000), clock=clock)


def test_public_session_can_only_access_resident_role():
    sessions = site()
    value = sessions.resident()
    identity = asyncio.run(sessions.verify(value['token']))
    assert identity.role == value['role'] == 'resident'
    assert identity.email == ''
    assert len(value['token'].split('.')) == 3
    with pytest.raises(InvalidIdentity):
        asyncio.run(sessions.verify(value['token'][:-1] + '!'))


def test_staff_password_is_checked_and_not_stored_in_session_metadata():
    sessions = site()
    with pytest.raises(HTTPException) as failure:
        sessions.login('wrong')
    assert failure.value.status_code == 401
    result = sessions.login('synthetic-manager')
    assert asyncio.run(sessions.verify(result['token'])).role == 'staff'
    assert 'synthetic-manager' not in str(sessions.entries)


def test_expiry_restart_and_bounds_do_not_turn_unknown_identity_into_staff():
    now = [1000.]
    sessions = site(lambda: now[0])
    result = sessions.resident()
    now[0] += 3601
    with pytest.raises(InvalidIdentity):
        asyncio.run(sessions.verify(result['token']))
    fresh = sessions.login('synthetic-manager')
    sessions.close()
    with pytest.raises(InvalidIdentity):
        asyncio.run(sessions.verify(fresh['token']))


def test_repeated_failed_passwords_are_bounded():
    sessions = site()
    for _ in range(5):
        with pytest.raises(HTTPException) as failure:
            sessions.login('wrong')
        assert failure.value.status_code == 401
    with pytest.raises(HTTPException) as failure:
        sessions.login('synthetic-manager')
    assert failure.value.status_code == 429


def test_public_http_entry_keeps_staff_data_and_settings_behind_password(seeded):
    from fastapi.testclient import TestClient

    from deploy.cloud.bootstrap import open_services
    from deploy.cloud.google_identity import GoogleIdentityVerifier
    from deploy.cloud.http_app import create_app
    from deploy.cloud.presentation import Presentation, install

    origin = 'https://neighbour.example'
    services = open_services(seeded[0], signing_key_loader=lambda: test_cloud_bootstrap.KEY)
    install(services.estate.db)
    sessions = site()
    verifier = GoogleIdentityVerifier('1.apps.googleusercontent.com', {'legacy-staff': 'staff'})
    app = create_app(services, verifier, origin=origin, site_access=sessions,
                     presentation=Presentation(services.estate))
    with TestClient(app, base_url=origin) as client:
        assert client.post('/api/v1/resident/access', json={}).status_code == 403
        assert client.post('/api/v1/resident/access', headers={'Origin': 'https://outside.invalid'}, json={}).status_code == 403
        assert client.post('/api/v1/resident/access', headers={'Origin': origin}, json={'role': 'staff'}).status_code == 422
        resident = client.post('/api/v1/resident/access', headers={'Origin': origin}, json={})
        assert resident.status_code == 200
        public = {'Origin': origin, 'Authorization': 'Bearer ' + resident.json()['token']}
        assert client.get('/api/v1/resident/session', headers=public).json()['role'] == 'resident'
        assert client.get('/api/v1/service-desk/requests', headers=public).status_code == 403
        assert client.get('/api/v1/service-desk/presentation', headers=public).status_code == 403
        assert 'persona' not in client.get('/api/v1/resident/presentation', headers=public).json()
        assert client.post('/api/v1/resident/access', headers={'Origin': origin}, json={'password': 'wrong'}).status_code == 401
        accepted = client.post('/api/v1/resident/access', headers={'Origin': origin}, json={'password': 'synthetic-manager'})
        staff = {'Origin': origin, 'Authorization': 'Bearer ' + accepted.json()['token']}
        assert client.get('/api/v1/service-desk/requests', headers=staff).status_code == 200
        settings = client.get('/api/v1/service-desk/presentation', headers=staff)
        assert settings.status_code == 200 and settings.json()['revision'] == 1
