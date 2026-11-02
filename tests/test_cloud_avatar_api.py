import hashlib

import pytest
import test_cloud_bootstrap
from fastapi.testclient import TestClient
from test_cloud_avatar_assets import model_zip
from test_cloud_site_access import site

from deploy.cloud.avatar_assets import install as install_models
from deploy.cloud.bootstrap import open_services
from deploy.cloud.google_identity import GoogleIdentityVerifier
from deploy.cloud.http_app import create_app
from deploy.cloud.presentation import Presentation, install

prepared = test_cloud_bootstrap.prepared
seeded = test_cloud_bootstrap.seeded
ORIGIN = 'https://neighbour.example'


@pytest.fixture
def models_api(seeded):
    services = open_services(seeded[0], signing_key_loader=lambda: test_cloud_bootstrap.KEY)
    install(services.estate.db)
    install_models(services.estate.db)
    verifier = GoogleIdentityVerifier('1.apps.googleusercontent.com', {'unused': 'staff'})
    app = create_app(services, verifier, origin=ORIGIN, site_access=site(), presentation=Presentation(services.estate))
    with TestClient(app, base_url=ORIGIN) as client:
        resident = client.post('/api/v1/resident/access', headers={'Origin': ORIGIN}, json={}).json()
        staff = client.post('/api/v1/resident/access', headers={'Origin': ORIGIN}, json={'password': 'synthetic-manager'}).json()
        yield client, {'Origin': ORIGIN, 'Authorization': 'Bearer ' + staff['token']}, {
            'Origin': ORIGIN, 'Authorization': 'Bearer ' + resident['token']}


def test_upload_then_publish_then_independent_resident_fetch_and_rollback(models_api):
    client, staff, resident = models_api
    content = model_zip()
    identity = 'cloud-live2d-' + hashlib.sha256(content).hexdigest()
    catalog = '/api/v1/service-desk/airi-models'
    upload = catalog + '/' + identity + '?name=PUBLIC-model.zip'
    download = '/api/v1/resident/airi-models/' + identity
    assert client.get(catalog).status_code == 401
    assert client.get(catalog, headers=resident).status_code == 403
    assert client.put(upload, headers={**resident, 'Content-Type': 'application/zip'}, content=content).status_code == 403
    result = client.put(upload, headers={**staff, 'Content-Type': 'application/zip'}, content=content)
    assert result.status_code == 200, result.text
    assert client.get(catalog, headers=staff).json()['items'][0]['id'] == identity
    assert client.get(download, headers=resident).status_code == 403
    assert client.get(download, headers=staff).content == content

    assert client.get(download).status_code == 401
    settings = client.get('/api/v1/service-desk/presentation', headers=staff).json()
    settings['expected_revision'] = settings.pop('revision')
    settings['airi']['stage_model'] = identity
    assert client.put('/api/v1/service-desk/presentation', headers=staff, json=settings).status_code == 200
    fresh = client.get(download, headers=resident)
    assert fresh.status_code == 200 and fresh.content == content
    assert fresh.headers['x-model-sha256'] == identity[13:]
    assert fresh.headers['cache-control'] == 'no-store'
    settings['expected_revision'] += 1
    settings['airi']['stage_model'] = 'preset-live2d-2'
    assert client.put('/api/v1/service-desk/presentation', headers=staff, json=settings).status_code == 200
    assert client.get(download, headers=resident).status_code == 403
    assert client.get(download, headers=staff).content == content


def test_invalid_archive_or_hash_does_not_publish_or_remove_existing_model(models_api):
    client, staff, _ = models_api
    prefix = '/api/v1/service-desk/airi-models'
    original = client.get('/api/v1/service-desk/presentation', headers=staff).json()
    for content in (b'not a zip', model_zip({'run.js': b'not allowed'})):
        identity = 'cloud-live2d-' + hashlib.sha256(content).hexdigest()
        result = client.put(prefix + '/' + identity + '?name=PUBLIC.zip',
                            headers={**staff, 'Content-Type': 'application/zip'}, content=content)
        assert result.status_code == 422
    assert client.get(prefix, headers=staff).json()['items'] == []
    assert client.get('/api/v1/service-desk/presentation', headers=staff).json() == original


def test_source_catalogue_is_staff_only_and_missing_cache_keeps_conversation_configuration(models_api):
    client, staff, resident = models_api
    path = '/api/v1/service-desk/model-gallery/catalogue'
    before = client.get('/api/v1/service-desk/presentation', headers=staff).json()
    assert client.get(path).status_code == 401
    assert client.get(path, headers=resident).status_code == 403
    result = client.get(path, headers=staff)
    assert result.status_code == 200 and result.json()['cache_unavailable']
    assert client.get('/api/v1/service-desk/presentation', headers=staff).json() == before
