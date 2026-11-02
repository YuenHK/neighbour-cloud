import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import test_cloud_bootstrap
import test_cloud_google_identity
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

pytest.importorskip('jwt', reason='optional cloud authentication research dependency')

prepared = test_cloud_bootstrap.prepared
seeded = test_cloud_bootstrap.seeded
keys = test_cloud_google_identity.keys
ORIGIN = 'https://neighbour.example'


@pytest.fixture
def api(seeded, keys, monkeypatch):
    from deploy.cloud.bootstrap import open_services
    from deploy.cloud.google_identity import GoogleIdentityVerifier
    from deploy.cloud.http_app import create_app
    from edge_hub import cloudflare_gemma
    from edge_hub.chat_gateway import completion_payload

    profile = seeded[0]
    services = open_services(profile, signing_key_loader=lambda: test_cloud_bootstrap.KEY)
    fetches, calls = [], []

    def jwks(request):
        fetches.append(request)
        return httpx.Response(200, json={'keys': [keys[1]]}, headers={'cache-control': 'max-age=300'})

    async def complete(payload, **kwargs):
        calls.append((payload, kwargs))
        return JSONResponse(completion_payload('公開回覆：記得你提過香蕉蛋糕。', 'gemma-cloudflare-free'))

    client = httpx.AsyncClient(transport=httpx.MockTransport(jwks))
    verifier = GoogleIdentityVerifier(test_cloud_google_identity.CLIENT,
        {'staff-subject': 'staff', 'resident-subject': 'resident'}, client=client)
    monkeypatch.setattr(cloudflare_gemma, 'complete', complete)
    search = AsyncMock(return_value={'answer': '公開垃圾分類資料。', 'search_status': 'cache'})
    monkeypatch.setattr(services.residents, 'search', search)
    staff = {'Authorization': 'Bearer ' + test_cloud_google_identity.token(keys), 'Origin': ORIGIN}
    resident = {'Authorization': 'Bearer ' + test_cloud_google_identity.token(keys, sub='resident-subject'), 'Origin': ORIGIN}
    try:
        app = create_app(services, verifier, origin=ORIGIN)
        with TestClient(app, base_url=ORIGIN, client=('198.51.100.12', 1000)) as browser:
            yield SimpleNamespace(client=browser, services=services, calls=calls, fetches=fetches,
                                  staff=staff, resident=resident, search=search, app=app)
    finally:
        services.close()
        asyncio.run(client.aclose())


def test_cloud_browser_timings_require_identity_and_accept_only_elapsed_marks(api):
    route = '/api/v1/resident/timing'
    assert api.client.post(route, headers={'Origin': ORIGIN}, json={'marks': {'first_text': 42}}).status_code == 401
    response = api.client.post(route, headers=api.resident, json={'marks': {'first_text': 42, 'first_audio_scheduled': 123}})
    assert response.status_code == 200 and response.json() == {'accepted': True}
    snapshot = api.app.app.state.browser_timings.snapshot()
    assert snapshot['stages']['first_text']['p50_ms'] == 42
    assert 'not audible acceptance' in snapshot['scope']
    for body in ({'marks': {'private-utterance': 10}}, {'marks': {'first_text': -1}},
                 {'marks': {'first_text': 180001}}, {'marks': {'first_text': 1}, 'text': 'PRIVATE'}):
        rejected = api.client.post(route, headers=api.resident, json=body)
        assert rejected.status_code == 422 and 'PRIVATE' not in rejected.text
    assert api.app.app.state.browser_timings.snapshot()['stages']['first_text']['samples'] == 1
    assert api.calls == [] and api.search.await_count == 0


def test_cloud_auth_cannot_be_replaced_by_native_operator_key_or_claimed_role(api):
    url = '/api/v1/service-desk/requests'
    assert api.client.get(url, headers={'X-Operator-Key': 'local-operator'}).status_code == 401
    assert api.client.get(url, headers={**api.resident, 'X-Operator-Key': 'claimed-staff'}).status_code == 403
    response = api.client.get(url, headers=api.staff)
    assert response.status_code == 200 and response.json()['items'][0]['case_number'] == 1
    assert response.headers['cache-control'] == 'no-store'
    assert len(api.fetches) == 1 and api.calls == []
    assert all('authorization' not in request.headers for request in api.fetches)


def test_three_turns_pass_full_history_to_fixed_gemma_and_search_does_not_create_case(api):
    history = []
    for text in ('今日整咗香蕉蛋糕。', '阿媽一齊幫手整。', '頭先提過邊個一齊整？'):
        history.append({'role': 'user', 'content': text})
        response = api.client.post('/api/v1/resident/chat', headers=api.resident, json={'messages': history})
        assert response.status_code == 200
        answer = response.json()['choices'][0]['message']['content']
        history.append({'role': 'assistant', 'content': answer})
    assert [len(body['messages']) for body, _ in api.calls] == [1, 3, 5]
    assert all(kwargs['prompt'] for _, kwargs in api.calls)
    before = api.services.cases.summary()
    response = api.client.post('/api/v1/resident/chat', headers=api.resident,
                               json={'messages': [{'role': 'user', 'content': '垃圾應該點樣分類？'}]})
    assert response.status_code == 200 and '分類資料' in response.text
    assert api.search.await_count == 1 and len(api.calls) == 3
    assert api.services.cases.summary() == before


def test_cloud_case_staff_update_and_short_number_progress_use_same_remote_store(api):
    response = api.client.post('/api/v1/service-desk/requests', headers=api.resident, json={
        'submission_id': 'e' * 32, 'kind': 'water', 'location': 'A座12樓B室',
        'message': '公開合成水喉漏水', 'confirmed': True})
    assert response.status_code == 200
    receipt = response.json()
    assert receipt['case_number'] == 2 and receipt['delivery_scope'] == 'cloud_staff_workbench_only'
    url = '/api/v1/service-desk/requests/' + receipt['id']
    update = {'status': 'acknowledged', 'expected_revision': 1, 'note': '已安排下午三點檢查'}
    assert api.client.patch(url, headers=api.resident, json=update).status_code == 403
    assert api.client.patch(url, headers=api.staff, json=update).status_code == 200
    progress = api.client.post('/api/v1/resident/chat', headers=api.resident,
        json={'messages': [{'role': 'user', 'content': '查個案2，A座12樓B室進度'}]})
    assert progress.status_code == 200 and '下午三點' in progress.text
    assert api.calls == []
    audit = api.services.journal.recent()
    assert any(item['actor'] == 'cloud_staff' and item['method'] == 'PATCH' for item in audit)
    assert any(item['actor'] == 'cloud_resident' and item['status'] == 403 for item in audit)


def test_model_adapter_only_gemma_and_csv_only_staff(api):
    from edge_hub.resident_models import GEMMA_MODEL
    body = {'model': GEMMA_MODEL, 'messages': [{'role': 'system', 'content': '親切鄰居'},
                                              {'role': 'user', 'content': '公開問候'}]}
    model = '/api/v1/resident/model/v1/chat/completions'
    assert api.client.post(model, headers=api.resident, json=body).status_code == 200
    assert '親切鄰居' in api.calls[0][1]['prompt']
    assert api.client.post(model, headers=api.resident, json={**body, 'model': 'other-model'}).status_code == 400
    assert len(api.calls) == 1
    assert api.client.get('/api/v1/events.csv', headers=api.resident).status_code == 403
    csv = api.client.get('/api/v1/events.csv', headers=api.staff)
    assert csv.status_code == 200 and 'synthetic-event' in csv.text
    assert api.services.events.export_metrics()['active'] == 0


def test_reject_cross_origin_missing_origin_http_duplicate_credentials_and_hidden_routes(api):
    url = '/api/v1/service-desk/requests'
    assert api.client.post(url, headers={**api.resident, 'Origin': 'https://other.example'}, json={}).status_code == 403
    assert api.client.post(url, headers={'Authorization': api.staff['Authorization']}, json={}).status_code == 403
    assert api.client.get(url, headers={**api.staff, 'Host': 'other.example'}).status_code == 403
    assert api.client.get('http://neighbour.example' + url, headers={**api.staff, 'X-Forwarded-Proto': 'https'}).status_code == 403
    duplicate = [('Authorization', api.staff['Authorization']), ('Authorization', api.resident['Authorization'])]
    assert api.client.get(url, headers=duplicate).status_code == 401
    for path in ('/robots', '/admin', '/settings', '/openapi.json', '/api/v1/ep/fleet/connect'):
        assert api.client.get(path, headers=api.staff).status_code == 404
    assert api.client.put('/api/v1/service-desk/search-settings', headers=api.staff,
                          json={'api_key': 'NEVER-SAVE'}).status_code == 404
    assert api.calls == []


def test_invalid_body_is_redacted_and_oversize_is_blocked_without_inference(api):
    response = api.client.post('/api/v1/resident/chat', headers=api.resident,
                               json={'messages': [{'role': 'private-invalid-role', 'content': 'PRIVATE-CONTENT'}]})
    assert response.status_code == 422 and 'PRIVATE' not in response.text
    huge = api.client.post('/api/v1/resident/chat', headers=api.resident, content='x' * 65537)
    assert huge.status_code == 413 and api.calls == []


def test_unmodified_native_resident_check_still_rejects_remote_browser(tmp_path):
    from edge_hub.service_desk import ServiceDeskStore, service_desk_router
    store = ServiceDeskStore(tmp_path / 'native.sqlite3')
    app = FastAPI()
    app.include_router(service_desk_router(store, lambda _: None,
        Path(__file__).resolve().parents[1] / 'edge_hub/static', AsyncMock()))
    try:
        with TestClient(app, base_url=ORIGIN, client=('198.51.100.12', 1)) as browser:
            assert browser.post('/api/v1/resident/chat', json={'messages': [{'role': 'user', 'content': '公開'}]}).status_code == 403
    finally:
        store.close()


@pytest.mark.parametrize('text', ['頭先提過邊個一齊整？', '啱啱 提到邊個幫手？',
                                  '剛才提到誰和我一起做？', '刚才提过什么？', '上一句講過邊個？'])
def test_conversation_reference_is_not_a_public_web_search(text):
    from edge_hub.estate_services import public_information_query
    assert not public_information_query(text)


def test_private_memory_context_does_not_silently_dispatch_to_cloud_or_local_model(api, monkeypatch):
    monkeypatch.setattr(api.services.residents, 'resolve', AsyncMock(return_value={
        'context': 'PRIVATE-MEMORY', 'local_only': True}))
    response = api.client.post('/api/v1/resident/chat', headers=api.resident,
        json={'messages': [{'role': 'user', 'content': '今日整咗香蕉蛋糕。'}], 'profile': 'public-test-name'})
    assert response.status_code == 503 and 'PRIVATE' not in response.text and api.calls == []


def test_gemma_error_has_no_other_provider_retry_and_scope_resets(api, monkeypatch):
    from deploy.cloud import http_app
    from edge_hub.resident_cloud import CloudUnavailable
    from edge_hub.storage_context import current_storage
    failed = AsyncMock(side_effect=CloudUnavailable('PRIVATE-UPSTREAM'))
    monkeypatch.setattr(http_app.cloudflare_gemma, 'complete', failed)
    response = api.client.post('/api/v1/resident/chat', headers=api.resident,
        json={'messages': [{'role': 'user', 'content': '今日整咗香蕉蛋糕。'}]})
    assert response.status_code == 503 and 'PRIVATE' not in response.text
    assert failed.await_count == 1
    assert http_app.current_principal() is None and current_storage() is None


def test_lifespan_always_closes_stores_even_if_identity_cleanup_fails(seeded, keys, monkeypatch):
    from deploy.cloud.bootstrap import open_services
    from deploy.cloud.google_identity import GoogleIdentityVerifier
    from deploy.cloud.http_app import create_app
    services = open_services(seeded[0], signing_key_loader=lambda: test_cloud_bootstrap.KEY)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail('no request needed')))
    verifier = GoogleIdentityVerifier(test_cloud_google_identity.CLIENT, {'staff-subject': 'staff'}, client=client)
    monkeypatch.setattr(verifier, 'aclose', AsyncMock(side_effect=RuntimeError('cleanup-failure')))
    try:
        with pytest.raises(RuntimeError, match='cleanup-failure'), TestClient(create_app(services, verifier, origin=ORIGIN)):
            pass
        assert services.closed
        with pytest.raises(RuntimeError, match='closed'):
            services.memory.items()
    finally:
        services.close()
        asyncio.run(client.aclose())


def test_readiness_checks_owned_configuration_without_provider_requests(api, monkeypatch):
    from deploy.cloud import airi_runtime
    checked = []
    def catalog():
        checked.append(True)
        return {'configured': {'cloudflare-workers-ai': True, 'microsoft-speech': True}}
    monkeypatch.setattr(airi_runtime, 'catalog', catalog)
    path = '/api/v1/resident/readiness'
    assert api.client.get(path).status_code == 401
    response = api.client.get(path, headers=api.resident)
    assert response.status_code == 200
    assert response.json()['provider_requests'] == 0
    assert response.json()['site_hardware'] is False
    assert checked == [True] and not api.calls
