import hashlib

import httpx
import pytest
import test_cloud_avatar_api as shared_api
from test_cloud_avatar_assets import model_zip
from test_cloud_avatar_vrm import model_vrm
from test_reviewed_model_imports import descriptor

from deploy.cloud import reviewed_model_imports
from deploy.cloud.reviewed_model_api import PATH

AGREEMENT = {'accepted_terms': True, 'application_use_only': True}
models_api = shared_api.models_api
seeded = shared_api.seeded
prepared = shared_api.prepared


def synthetic_importer(client, raw):
    calls = []
    row = descriptor(raw)
    importer = client.app.app.state.reviewed_models
    importer._models = {row.id: row}

    def upstream(request):
        calls.append(request)
        assert str(request.url) == row.download_url
        assert 'authorization' not in request.headers and 'cookie' not in request.headers
        return httpx.Response(200, stream=httpx.ByteStream(raw))

    importer._transport = httpx.MockTransport(upstream)
    return row, calls


def test_catalogue_and_preview_are_staff_only_and_do_not_fetch_in_background(models_api):
    client, staff, resident = models_api
    before = client.get('/api/v1/service-desk/presentation', headers=staff).json()
    assert client.get(PATH).status_code == 401
    assert client.get(PATH, headers=resident).status_code == 403
    result = client.get(PATH, headers=staff)
    assert result.status_code == 200
    assert len(result.json()['items']) == 9 and result.json()['auto_publish'] is False
    assert all('download_url' not in row for row in result.json()['items'])
    for headers, status in (({'Origin': staff['Origin']}, 401), (resident, 403)):
        response = client.post(PATH + '/onair-miko/preview', json=AGREEMENT, headers=headers)
        assert response.status_code == status
    assert client.post(PATH + '/onair-miko/preview', json={}, headers=resident).status_code == 403
    assert client.get('/api/v1/service-desk/presentation', headers=staff).json() == before
    assert client.get('/api/v1/service-desk/airi-models', headers=staff).json()['items'] == []


@pytest.mark.parametrize('body', [{}, {'accepted_terms': True},
    {'accepted_terms': False, 'application_use_only': True},
    {'accepted_terms': True, 'application_use_only': False},
    {'accepted_terms': 1, 'application_use_only': 1},
    {**AGREEMENT, 'download_url': 'https://127.0.0.1/private'}])
def test_preview_requires_explicit_application_scope_and_no_url_override(models_api, body):
    client, staff, _ = models_api
    row, calls = synthetic_importer(client, model_vrm())
    response = client.post(PATH + '/' + row.id + '/preview', json=body, headers=staff)
    assert response.status_code == 422 and calls == []


def test_preview_then_existing_save_publishes_with_credit_and_keeps_original_content(models_api):
    client, staff, resident = models_api
    raw = model_vrm()
    row, calls = synthetic_importer(client, raw)
    before = client.get('/api/v1/service-desk/presentation', headers=staff).json()
    response = client.post(PATH + '/' + row.id + '/preview', json=AGREEMENT, headers=staff)
    assert response.status_code == 200 and response.content == raw and len(calls) == 1
    assert response.headers['x-model-sha256'] == hashlib.sha256(raw).hexdigest()
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-disposition'].startswith('inline;')
    assert client.get('/api/v1/service-desk/airi-models', headers=staff).json()['items'] == []
    assert client.get('/api/v1/service-desk/presentation', headers=staff).json() == before
    identity = 'cloud-vrm-' + row.sha256
    saved = client.put('/api/v1/service-desk/airi-models/' + identity + '?name=Approved.vrm',
                       headers={**staff, 'Content-Type': 'model/gltf-binary'}, content=raw)
    assert saved.status_code == 200
    before['expected_revision'] = before.pop('revision')
    before['airi']['stage_model'] = identity
    assert client.put('/api/v1/service-desk/presentation', headers=staff, json=before).status_code == 200
    public = client.get('/api/v1/resident/presentation', headers=resident)
    assert public.status_code == 200
    assert public.json()['model_credit'] == {'name': row.name, 'author': row.credit,
        'source': row.source_url, 'terms': row.license_url, 'notice': row.notice}
    assert client.get('/api/v1/resident/airi-models/' + identity, headers=resident).content == raw


def test_unknown_id_never_fetches_and_changed_file_is_not_published(models_api):
    client, staff, _ = models_api
    row, calls = synthetic_importer(client, model_vrm())
    response = client.post(PATH + '/not-reviewed/preview', json=AGREEMENT, headers=staff)
    assert response.status_code == 404 and calls == []
    client.app.app.state.reviewed_models._transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'changed'))
    response = client.post(PATH + '/' + row.id + '/preview', json=AGREEMENT, headers=staff)
    assert response.status_code == 422 and response.json()['detail']['code'] == 'model_changed_requires_review'
    assert client.get('/api/v1/service-desk/airi-models', headers=staff).json()['items'] == []


def test_static_original_credit_survives_shared_publication_and_clears_on_other_model(models_api, monkeypatch):
    client, staff, resident = models_api
    raw = model_zip()
    identity = 'cloud-live2d-' + hashlib.sha256(raw).hexdigest()
    original_credit = dict(next(iter(reviewed_model_imports.STATIC_MODEL_CREDITS.values())))
    # Synthetic bounded model exercises the same exact-ID lookup without copying
    # the original artist's runtime binary into the test suite.
    monkeypatch.setattr(reviewed_model_imports, 'STATIC_MODEL_CREDITS', {identity: original_credit})
    assert client.put('/api/v1/service-desk/airi-models/' + identity + '?name=synthetic-cat.zip',
                      headers={**staff, 'Content-Type': 'application/zip'}, content=raw).status_code == 200
    settings = client.get('/api/v1/service-desk/presentation', headers=staff).json()
    settings['expected_revision'] = settings.pop('revision')
    settings['airi']['stage_model'] = identity
    assert client.put('/api/v1/service-desk/presentation', headers=staff, json=settings).status_code == 200
    assert client.get('/api/v1/resident/presentation', headers=resident).json()['model_credit'] == original_credit
    assert client.get('/api/v1/resident/airi-models/' + identity, headers=resident).content == raw
    settings['expected_revision'] += 1
    settings['airi']['stage_model'] = 'preset-live2d-2'
    assert client.put('/api/v1/service-desk/presentation', headers=staff, json=settings).status_code == 200
    assert 'model_credit' not in client.get('/api/v1/resident/presentation', headers=resident).json()
