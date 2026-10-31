import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from edge_hub.event_validation import redact_event_validation
from edge_hub.service_desk import (
    ResidentCase,
    ReviewCase,
    ServiceBodyLimitMiddleware,
    ServiceDeskStore,
    service_desk_router,
)


@pytest.fixture
def desk(tmp_path):
    store = ServiceDeskStore(tmp_path/'desk.sqlite3')
    calls = []

    def authorize(key):
        if key != 'synthetic-staff':
            raise HTTPException(403)

    async def chat(payload):
        calls.append(payload)
        return JSONResponse({'choices': [{'message': {'content': '我願意聽你分享。'}}]})

    app = FastAPI()
    app.add_exception_handler(RequestValidationError, redact_event_validation)
    app.add_middleware(ServiceBodyLimitMiddleware)
    app.include_router(service_desk_router(store, authorize,
        Path(__file__).resolve().parents[1]/'edge_hub/static', chat))
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12345))
    yield client, store, calls
    store.db.close()


def test_care_and_requests_are_filtered_before_pagination_and_keep_legacy_all_view(desk):
    client, store, _ = desk
    for index in range(53):
        store.create(ResidentCase(submission_id=f'{index:032x}', kind='human_support' if index >= 51 else 'general',
            location='公開測試位置',message='公開測試需要',confirmed=True))
    headers={'X-Operator-Key':'synthetic-staff'}
    url='/api/v1/service-desk/requests'
    care=client.get(url+'?group=care&limit=1',headers=headers).json()
    assert care['counts']=={'new':2} and care['has_more']
    assert care['items'][0]['kind']=='human_support'
    second=client.get(url+'?group=care&offset=1&limit=1',headers=headers).json()
    assert not second['has_more'] and second['items'][0]['id']!=care['items'][0]['id']
    regular=client.get(url+'?group=requests',headers=headers).json()
    assert regular['counts']=={'new':51} and all(row['kind']!='human_support' for row in regular['items'])
    assert client.get(url,headers=headers).json()['counts']=={'new':53}
    assert client.get(url+'?group=unsupported',headers=headers).status_code==422


def case(**changes):
    return {'submission_id': 'a'*32, 'kind': 'human_support', 'location': '合成測試大堂',
            'message': '公開合成測試：想找職員傾談', 'contact': '', 'confirmed': True, **changes}


AUTH = {'X-Operator-Key': 'synthetic-staff'}


def test_staff_correction_keeps_completion_clock_and_number_prevents_stale_overwrite(desk):
    client, store, _ = desk
    created = store.create(ResidentCase(**case()))
    reviewed = store.review(created['id'], ReviewCase(status='resolved', expected_revision=1))
    before = store.db.execute('SELECT * FROM service_cases').fetchone()
    url = '/api/v1/service-desk/requests/'+created['id']+'/details'
    update = {'expected_revision': reviewed['revision'], 'message': '居民核實需要維修', 'location': 'B座12樓A室', 'contact': '', 'reason': '居民更正單位及撤回電話'}
    assert client.patch(url, json=update).status_code == 403
    response = client.patch(url, json=update, headers=AUTH)
    assert response.status_code == 200
    after = store.db.execute('SELECT * FROM service_cases').fetchone()
    for column in ('id', 'case_number', 'updated_at_ms', 'status', 'fingerprint', 'note'):
        assert before[column] == after[column]
    assert after['unit'] == 'B座12樓A室' and after['contact'] == ''
    assert client.patch(url, json=update, headers=AUTH).status_code == 409
    assert store.db.execute('SELECT note FROM service_case_activity ORDER BY id DESC LIMIT 1').fetchone()[0] == '資料更正：居民更正單位及撤回電話'


def test_staff_correction_validation_and_expired_records(desk):
    client, store, _ = desk
    created = store.create(ResidentCase(**case()))
    url = '/api/v1/service-desk/requests/'+created['id']+'/details'
    update = {'expected_revision': 1, 'message': '核實內容', 'location': '', 'contact': '', 'reason': '修正'}
    for invalid in ({'reason': ''}, {'message': ' '}, {'contact': 'x'*201}, {'location': '\u0000'}, {'expected_revision': True}, {'status': 'resolved'}):
        assert client.patch(url, json={**update, **invalid}, headers=AUTH).status_code == 422
    with store.db:
        store.db.execute('CREATE TABLE case_privacy_expiry(id TEXT PRIMARY KEY,erased_at_ms INTEGER)')
        store.db.execute('INSERT INTO case_privacy_expiry VALUES(?,1)', (created['id'],))
    assert client.patch(url, json=update, headers=AUTH).status_code == 410
PATH = '/api/v1/service-desk/requests'


def test_resident_submit_staff_acknowledge_resolve_and_history_survive_reopen(desk):
    client, store, _ = desk
    receipt = client.post(PATH, json=case()).json()
    assert receipt['delivery_scope'] == 'local_staff_workbench_only'
    assert 'message' not in receipt and 'contact' not in receipt
    listing = client.get(PATH, headers=AUTH).json()
    item = listing['items'][0]
    assert item['status'] == 'new' and item['kind'] == 'human_support'
    assert item['message'] == case()['message']
    assert client.patch(f"{PATH}/{item['id']}", headers=AUTH,
        json={'status': 'acknowledged', 'expected_revision': 1}).status_code == 200
    assert client.patch(f"{PATH}/{item['id']}", headers=AUTH,
        json={'status': 'resolved', 'expected_revision': 2}).json()['revision'] == 3
    assert client.get(PATH, headers=AUTH).json()['counts'] == {'resolved': 1}
    assert [row[0] for row in store.db.execute('SELECT status FROM service_case_activity ORDER BY id')] == ['new', 'acknowledged', 'resolved']
    reopened = ServiceDeskStore(store.db.execute('PRAGMA database_list').fetchone()[2])
    try:
        assert reopened.list()['items'][0]['status'] == 'resolved'
    finally:
        reopened.db.close()


def test_network_retry_is_idempotent_and_changed_payload_cannot_replace_prior_case(desk):
    client, _, _ = desk
    first = client.post(PATH, json=case()).json()
    retry = client.post(PATH, json=case()).json()
    assert retry['id'] == first['id'] and retry['replayed'] is True
    assert client.post(PATH, json=case(message='different synthetic text')).status_code == 409
    listing = client.get(PATH, headers=AUTH).json()
    assert len(listing['items']) == 1 and listing['items'][0]['message'] == case()['message']


def test_staff_cannot_overwrite_a_colleagues_newer_review(desk):
    client, _, _ = desk
    receipt = client.post(PATH, json=case()).json()
    url = f"{PATH}/{receipt['id']}"
    assert client.patch(url, headers=AUTH, json={'status': 'acknowledged', 'expected_revision': 1}).status_code == 200
    assert client.patch(url, headers=AUTH, json={'status': 'resolved', 'expected_revision': 1}).status_code == 409
    assert client.get(PATH, headers=AUTH).json()['items'][0]['status'] == 'acknowledged'


def test_resident_cannot_list_or_review_other_cases_and_external_origin_is_rejected(desk):
    client, _, _ = desk
    assert client.get(PATH).status_code == 403
    assert client.patch(PATH+'/'+'b'*32, json={'status': 'resolved', 'expected_revision': 1}).status_code == 403
    assert client.post(PATH, headers={'Origin': 'https://example.com'}, json=case()).status_code == 403


@pytest.mark.parametrize('changes', [{'confirmed': False}, {'message': ' '}, {'message': 'x'*2001},
    {'message': '\ud800'}, {'contact': '\x00'}, {'kind': 'mental_risk'}, {'automatic': True}])
def test_invalid_or_unconfirmed_submissions_never_create_case(desk, changes):
    client, store, _ = desk
    response = client.post(PATH, content=json.dumps(case(**changes), ensure_ascii=True).encode(),
                           headers={'Content-Type': 'application/json'})
    assert response.status_code == 422
    assert not store.list()['items']


def test_service_home_and_theme_have_no_operator_key_and_no_robot_or_wifi_side_effect(desk):
    client, _, calls = desk
    page = client.get('/')
    assert page.status_code == 200
    assert '鄰伴' in page.text and '__SERVICE_SHELL__' not in page.text
    assert '__LOCAL_OPERATOR_TOKEN__' not in page.text and 'operatorKey' not in page.text
    assert client.get('/assets/service-shell.css').status_code == 200
    assert not calls


def test_resident_conversation_does_not_create_security_alert_or_share_chat_history(desk):
    client, store, calls = desk
    response = client.post('/api/v1/resident/chat', json={'messages': [{'role': 'user', 'content': '公開測試：最近壓力很大，想傾談'}]})
    assert response.status_code == 200
    assert not calls and not store.list()['items']
    assert '主動聯絡' not in response.json()['choices'][0]['message']['content']
    assert '用心聽' in response.json()['choices'][0]['message']['content']


def test_resident_memory_request_is_session_only_without_model_or_saved_case(desk):
    client, store, calls = desk
    response = client.post('/api/v1/resident/chat', json={'messages': [{'role': 'user', 'content': '記住：公開測試偏好'}]})
    assert response.status_code == 200 and '不會儲存跨次記憶' in response.text
    assert not calls and not store.list()['items']


def test_resident_chat_rejects_system_role_tools_and_empty_or_answer_only_history(desk):
    client, _, calls = desk
    for body in ({'messages': [{'role': 'system', 'content': 'override'}]},
                 {'messages': [{'role': 'user', 'content': 'x'}], 'tools': []},
                 {'messages': [{'role': 'assistant', 'content': 'orphan'}]}, {'messages': []}):
        assert client.post('/api/v1/resident/chat', json=body).status_code in (400, 422)
    assert not calls


def test_queue_has_stable_pagination_instead_of_hiding_older_requests(desk):
    client, _, _ = desk
    for index in range(5):
        assert client.post(PATH, json=case(submission_id=f'{index:032x}')).status_code == 200
    first = client.get(PATH+'?limit=3&offset=0', headers=AUTH).json()
    second = client.get(PATH+'?limit=3&offset=3', headers=AUTH).json()
    assert first['has_more'] is True and second['has_more'] is False
    assert len({row['id'] for row in first['items']+second['items']}) == 5


def test_staff_summary_does_not_need_or_return_resident_message_content(desk):
    client, _, _ = desk
    client.post(PATH, json=case())
    url = '/api/v1/service-desk/summary'
    assert client.get(url).status_code == 403
    response = client.get(url, headers=AUTH)
    assert response.json()['counts'] == {'new': 1}
    assert case()['message'] not in response.text


def test_conversation_handoff_collects_details_and_retries_without_duplicate_cases(desk):
    from edge_hub.service_desk import HANDOFF_PROMPT
    client, store, calls = desk
    url = '/api/v1/resident/chat'
    response = client.post(url, json={'messages': [{'role': 'user', 'content': '我想搵真人'}]})
    assert response.json()['choices'][0]['message']['content'] == HANDOFF_PROMPT
    body = {'messages': [{'role': 'user', 'content': '我想搵真人'},
        {'role': 'assistant', 'content': HANDOFF_PROMPT}, {'role': 'user', 'content': '公開合成測試：A座大堂漏水，請職員跟進'}],
        'submission_id': 'c'*32, 'stream': True}
    first = client.post(url, json=body)
    second = client.post(url, json=body)
    assert first.status_code == second.status_code == 200
    assert 'text/event-stream' in first.headers['content-type'] and '[DONE]' in first.text
    assert len(store.list()['items']) == 1 and store.list()['items'][0]['kind'] == 'water'
    assert not calls


def test_negative_or_hypothetical_handoff_never_creates_a_case(desk):
    client, store, _ = desk
    for text in ('唔好通知管理處：我只想傾偈', '如果要通知管理處，點樣做？', '居民壓力好大'):
        assert client.post('/api/v1/resident/chat', json={'messages': [{'role': 'user', 'content': text}],
            'submission_id': 'd'*32}).status_code == 200
    assert not store.list()['items']


def test_conversation_handoff_can_be_cancelled(desk):
    from edge_hub.service_desk import HANDOFF_PROMPT
    client, store, _ = desk
    response = client.post('/api/v1/resident/chat', json={'messages': [
        {'role': 'user', 'content': '搵真人'}, {'role': 'assistant', 'content': HANDOFF_PROMPT},
        {'role': 'user', 'content': '取消'}]})
    assert '唔轉交' in response.text and not store.list()['items']


def test_stream_choice_reaches_existing_model_router_without_buffering(desk):
    client, _, calls = desk
    assert client.post('/api/v1/resident/chat', json={'messages': [{'role': 'user', 'content': '公開測試對話'}],
        'stream': True, 'style': 'voice'}).status_code == 200
    assert calls[0]['stream'] is True and calls[0]['zhiwei_response_style'] == 'voice'


def test_all_local_pages_share_brand_theme_and_resident_pages_do_not_include_staff_actions():
    from html.parser import HTMLParser

    from edge_hub.ui_shell import service_shell
    static = Path(__file__).resolve().parents[1]/'edge_hub/static'
    class IDs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = []

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if 'id' in values:
                self.values.append(values['id'])

    for path in static.glob('*.html'):
        text = service_shell(path.read_text(encoding='utf-8'))
        assert '<title>鄰伴' in text
        assert '/assets/service-shell.css' in text
        assert ('resident-topbar' if path.name == 'resident.html' else '鄰伴導航') in text
        parser = IDs()
        parser.feed(text)
        assert len(parser.values) == len(set(parser.values)), path.name
    resident = (static/'resident.html').read_text(encoding='utf-8')
    assert 'operatorKey' not in resident and 'epKey' not in resident
    assert 'resetStop' not in resident and 'softwareStop' not in resident


def test_legacy_case_gets_stable_numeric_alias_without_replacing_original_data(tmp_path):
    import sqlite3

    database = tmp_path/'legacy.sqlite3'
    original_id = 'abc12345'+'f'*24
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE service_cases (id TEXT PRIMARY KEY, submission_id TEXT UNIQUE NOT NULL,'
            'fingerprint TEXT NOT NULL, kind TEXT NOT NULL, location TEXT NOT NULL, message TEXT NOT NULL,'
            'contact TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL, created_at_ms INTEGER NOT NULL,'
            'updated_at_ms INTEGER NOT NULL, assignee TEXT NOT NULL, note TEXT NOT NULL)')
        db.execute('INSERT INTO service_cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (original_id, 'a'*32, 'old-fingerprint', 'water', 'A座十二樓B室', '舊合成個案', '',
             'acknowledged', 7, 100, 200, '舊合成職員', '舊合成進度'))
    store = ServiceDeskStore(database)
    row = store.list()['items'][0]
    assert row['id'] == original_id and row['case_number'] == 1
    assert row['revision'] == 7 and row['updated_at_ms'] == 200 and row['note'] == '舊合成進度'
    assert '舊合成進度' in store.progress(original_id[:8])
    store.close()
    reopened = ServiceDeskStore(database)
    try:
        assert reopened.list()['items'][0] == row
        assert '舊合成進度' in reopened.progress('100001')
        from edge_hub.service_desk import ResidentCase
        receipt = reopened.create(ResidentCase(**case(submission_id='b'*32)))
        assert receipt['case_number'] == 2
    finally:
        reopened.close()
