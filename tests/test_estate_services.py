import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from edge_hub.estate_services import (
    EstateStore,
    KnowledgeEdit,
    ResidentServices,
    estate_router,
    public_information_query,
)
from edge_hub.service_desk import ServiceDeskStore, service_desk_router


@pytest.fixture
def estate(tmp_path, monkeypatch):
    monkeypatch.setattr('edge_hub.estate_services.search_key', lambda: '')
    cases = ServiceDeskStore(tmp_path/'cases.sqlite3')
    facts = EstateStore(tmp_path/'facts.sqlite3')
    services = ResidentServices(facts, cases)
    calls = []
    async def chat(payload):
        calls.append(payload)
        return JSONResponse({'choices': [{'message': {'content': '合成回覆'}}]})
    app = FastAPI()
    app.include_router(service_desk_router(cases, lambda key: None,
        Path(__file__).resolve().parents[1]/'edge_hub/static', chat, services))
    app.include_router(estate_router(facts, lambda key: None))
    yield TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 1)), cases, facts, calls
    cases.close()
    facts.close()


def turn(client, text, history=None, **extra):
    return client.post('/api/v1/resident/chat', json={'messages': [*(history or []), {'role': 'user', 'content': text}], **extra})


def answer(response):
    assert response.status_code == 200
    return response.json()['choices'][0]['message']['content']


def test_unified_quota_script_is_available_through_the_operational_asset_route(estate):
    client, *_ = estate
    response = client.get('/assets/service/api-quota.js')
    assert response.status_code == 200
    assert 'ZhiweiQuota' in response.text
    assert 'javascript' in response.headers['content-type']
    assert response.headers['cache-control'] == 'no-store'


def test_native_search_shares_resident_cache_and_never_exposes_key(estate, monkeypatch):
    client, *_ = estate
    monkeypatch.setattr('edge_hub.estate_services.search_key', lambda: 'private-test-key')
    settings = client.get('/api/v1/resident/search-settings')
    assert settings.json() == {'configured': True, 'managed': True}
    assert 'private-test-key' not in settings.text
    assert client.get('/api/v1/resident/search-settings', headers={'Origin': 'https://outside.invalid'}).status_code == 403
    assert client.post('/api/v1/resident/search', json={'query': '公開資料', 'time_range': 'week'}).status_code == 400


def test_conversation_recall_is_not_public_web_search():
    assert not public_information_query('頭先講嗰樣嘢，我仲未有精神去做。你記得係咩嗎？')
    assert not public_information_query('你仲記唔記得我啱啱講咩？')
    assert public_information_query('香港科學館今日幾點開門？')


def test_search_normalizes_and_coalesces_simultaneous_native_and_resident_requests(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setattr('edge_hub.estate_services.search_key', lambda: 'synthetic-only')
    reply = httpx.Response(200, request=httpx.Request('POST', 'https://api.tavily.com/search'),
        json={'results': [{'title': 'Official', 'url': 'https://example.org/', 'content': 'Public'}]})
    network = SimpleNamespace(post=AsyncMock(return_value=reply))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=network)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr('edge_hub.estate_services.httpx.AsyncClient', lambda **kwargs: context)

    async def run():
        services = ResidentServices(None, None)
        a, b = await asyncio.gather(services.search('香港  資料'), services.search('香港 資料'))
        assert a['sources'] == b['sources']
        assert (await services.search('香港　資料'))['search_status'] == 'cache'
        assert network.post.await_count == 1
        assert not services.search_pending
    asyncio.run(run())


def test_named_memory_survives_new_session_and_does_not_cross_profiles(estate):
    client, _, facts, _ = estate
    assert '阿明' in answer(turn(client, '我叫阿明'))
    assert '記住咗' in answer(turn(client, '記住：我鍾意晨早散步', profile='阿明'))
    assert len(facts.memories('阿明')) == 1
    assert '晨早散步' in answer(turn(client, '你記得我啲咩', profile='阿明'))
    assert '未有' in answer(turn(client, '你記得我啲咩', profile='另一位'))


def test_memory_without_name_collects_a_name_then_really_saves(estate):
    client, _, facts, _ = estate
    prompt = answer(turn(client, '記住：我需要無障礙通道'))
    history = [{'role': 'user', 'content': '記住：我需要無障礙通道'}, {'role': 'assistant', 'content': prompt}]
    assert '記住' in answer(turn(client, '我叫阿欣', history))
    assert facts.memories('阿欣')[0]['text'] == '我需要無障礙通道'


def test_relevant_resident_facts_use_local_only_and_ordinary_chat_is_not_stored(estate):
    client, _, facts, calls = estate
    facts.remember('阿明', '我喜歡早上在花園散步')
    answer(turn(client, '我喜歡早上做甚麼？', profile='阿明'))
    assert calls[-1]['_local_only'] is True and '花園散步' in calls[-1]['_service_context']
    answer(turn(client, '我今日工作好攰'))
    assert len(facts.memories('阿明')) == 1


def test_knowledge_editor_revision_history_and_instant_resident_answer(estate):
    client, _, facts, calls = estate
    identity = 'e'*32
    edit = {'title': '合成測試管理處時間', 'keywords': ['管理處幾點', '開放時間'],
        'answer': '合成測試：早上九點至下午六點。', 'enabled': True, 'expected_revision': 0}
    path = '/api/v1/service-desk/knowledge/'+identity
    assert client.put(path, json=edit).status_code == 200
    assert '九點' in answer(turn(client, '管理處幾點開門？'))
    assert not calls
    assert client.put(path, json=edit).status_code == 409
    edit.update(expected_revision=1, enabled=False)
    assert client.put(path, json=edit).status_code == 200
    assert facts.answer('管理處幾點') is None
    assert facts.db.execute('SELECT COUNT(*) FROM estate_knowledge_history').fetchone()[0] == 2


def test_natural_help_extracts_place_and_contact_and_staff_can_reply(estate):
    client, cases, _, _ = estate
    response = turn(client, '想搵人幫手處理漏水，A座大堂，電話23456789', submission_id='a'*32)
    assert '傳到管理工作台' in answer(response)
    row = cases.list()['items'][0]
    assert 'A座' in row['location'] and row['contact'] == '23456789'
    path = '/api/v1/service-desk/requests/'+row['id']
    assert client.patch(path, json={'status': 'acknowledged', 'expected_revision': 1,
        'assignee': '合成職員', 'note': '已安排到場檢查'}).status_code == 200
    assert '已安排到場' in answer(turn(client, '查詢求助'+row['id'][:8]))
    assert cases.summary()['counts'] == {'acknowledged': 1}


def test_old_all_digit_receipt_does_not_collide_with_new_numeric_case_reference(estate):
    client, cases, _, _ = estate
    answer(turn(client, '想搵人幫手處理漏水，A座大堂', submission_id='d'*32))
    row = cases.list()['items'][0]
    # A real UUID prefix can contain only digits. Make the old flaky case deterministic.
    with cases.db:
        cases.db.execute('UPDATE service_cases SET id=? WHERE id=?', ('46548249'+'a'*24, row['id']))
        cases.db.execute('UPDATE service_case_numbers SET case_id=? WHERE case_id=?', ('46548249'+'a'*24, row['id']))
    assert '我幫你查到' in answer(turn(client, '查詢求助46548249'))
    assert '暫時對唔上' in answer(turn(client, '個案編號46548249'))
    assert '我幫你查到' in answer(turn(client, '個案編號'+str(row['case_number'])))


def test_false_or_hypothetical_help_never_creates_case(estate):
    client, cases, _, _ = estate
    for text in ('唔好搵人處理漏水，我只係問吓', '如果大堂漏水，點樣搵人幫手？'):
        answer(turn(client, text, submission_id='b'*32))
    assert not cases.list()['items']


def test_additive_case_migration_preserves_legacy_case(estate):
    _, cases, _, _ = estate
    from edge_hub.service_desk import ResidentCase
    receipt = cases.create(ResidentCase(submission_id='f'*32, kind='general', message='合成舊項目', confirmed=True))
    reopened = ServiceDeskStore(cases.db.execute('PRAGMA database_list').fetchone()[2])
    try:
        assert reopened.list()['items'][0]['id'] == receipt['id']
        assert reopened.list()['items'][0]['message'] == '合成舊項目'
    finally:
        reopened.close()


def test_named_conversation_stays_local_even_without_relevant_facts(estate):
    client, _, _, calls = estate
    answer(turn(client, '今日想傾吓偈', profile='合成稱呼'))
    assert calls[-1]['_local_only'] is True
    answer(turn(client, '今日想傾吓偈'))
    assert '_local_only' not in calls[-1]


def test_search_uses_only_explicit_query_and_real_results(estate, monkeypatch):
    client, cases, _, calls = estate
    import edge_hub.estate_services as module
    monkeypatch.setattr(module, 'search_key', lambda: 'synthetic-search-key')
    sent = []
    def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={'results': [{'title': '合成官方資料', 'url': 'https://example.org/info', 'content': '合成摘要'}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    answer(turn(client, '上網查香港公共圖書館', [{'role': 'user', 'content': '不應傳到搜尋的舊聊天'}]))
    assert sent[0]['query'] == '香港公共圖書館' and '舊聊天' not in json.dumps(sent)
    assert 'https://example.org/info' in calls[0]['_service_context']
    assert not cases.list()['items']


def test_native_ollama_disables_thinking_and_keeps_stream_live():
    from edge_hub.resident_inference import native_local
    captured = []
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, text='\n'.join([json.dumps({'message': {'thinking': 'not shown', 'content': '你好。'}, 'done': False}), json.dumps({'done': True})]))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            response = await native_local({'messages': [{'role': 'user', 'content': '你好'}], 'stream': True}, client=client)
            result = b''.join([piece async for piece in response.body_iterator]).decode()
            assert '你好' in result and 'not shown' not in result and '[DONE]' in result
            assert captured[0]['think'] is False and captured[0]['options']['num_gpu'] == 99
            assert not client.is_closed
    asyncio.run(scenario())


def test_help_collects_missing_location_without_losing_original_issue(estate):
    client, cases, _, _ = estate
    first = '想搵人幫手處理漏水'
    prompt = answer(turn(client, first, submission_id='1'*32))
    assert '位置' in prompt and not cases.list()['items']
    history = [{'role': 'user', 'content': first}, {'role': 'assistant', 'content': prompt}]
    assert '傳到管理工作台' in answer(turn(client, 'B座十樓走廊', history, submission_id='2'*32))
    case = cases.list()['items'][0]
    assert case['location'] == 'B座十樓走廊' and first in case['message']


def test_forgetting_one_resident_fact_keeps_other_resident_and_original_record(estate):
    client, _, facts, _ = estate
    facts.remember('阿明', '我喜歡晨早散步')
    facts.remember('阿欣', '我喜歡晨早散步')
    assert '唔會再用' in answer(turn(client, '忘記：我喜歡晨早散步', profile='阿明'))
    assert not facts.memories('阿明') and facts.memories('阿欣')
    assert facts.db.execute('SELECT COUNT(*) FROM resident_memories').fetchone()[0] == 2


def test_report_without_magic_words_routes_once_and_returns_numeric_reference(estate):
    client, cases, _, calls = estate
    first = answer(turn(client, 'A座十二樓B室水喉漏水', submission_id='3'*32))
    row = cases.list()['items'][0]
    assert row['case_number'] == 1 and row['team'] == '維修跟進'
    assert row['unit'] == 'A座12樓B室' and '編號 1' in first
    assert '唔使再搵同事' in first and not calls
    answer(turn(client, 'A座十二樓B室水喉漏水', submission_id='3'*32))
    assert len(cases.list()['items']) == 1
    assert cases.db.execute('SELECT COUNT(*) FROM service_case_numbers').fetchone()[0] == 1


@pytest.mark.parametrize('phrase', ['個案100001進度', '我係一零零零零一號個案，想查進度',
    '查編號一〇〇〇〇一', '查十萬零一嘅進度', '編號1 0 0 0 0 1，A座12樓B室查進度'])
def test_voice_numbers_return_actual_latest_staff_reply(estate, phrase):
    client, cases, _, _ = estate
    answer(turn(client, 'A座十二樓B室水喉漏水', submission_id='4'*32))
    row = cases.list()['items'][0]
    assert client.patch('/api/v1/service-desk/requests/'+row['id'], json={
        'status': 'acknowledged', 'expected_revision': 1, 'assignee': '合成職員', 'note': '已安排師傅下午三點檢查'}).status_code == 200
    result = answer(turn(client, phrase))
    assert '下午三點' in result and '正在跟進' in result and len(cases.list()['items']) == 1


def test_unit_query_disambiguates_cases_and_followup_digits_choose_one(estate):
    client, cases, _, _ = estate
    answer(turn(client, 'A座十二樓B室水喉漏水', submission_id='5'*32))
    result = answer(turn(client, '我係A座12樓B，想查進度'))
    assert '個案 1' in result
    answer(turn(client, 'A座十二樓B室冷氣壞咗', submission_id='6'*32))
    prompt = answer(turn(client, '我係A座12樓B室，想查進度'))
    assert '多過一個' in prompt and '2' in prompt
    result = answer(turn(client, '100001', [{'role': 'user', 'content': '查單位進度'}, {'role': 'assistant', 'content': prompt}]))
    assert '個案 1' in result and '多過一個' not in result
    assert len(cases.list()['items']) == 2


def test_numeric_reference_and_unit_must_match_and_unknown_is_not_invented(estate):
    client, cases, _, _ = estate
    answer(turn(client, 'A座十二樓B室水喉漏水', submission_id='7'*32))
    assert '對唔上' in answer(turn(client, '查個案100001，B座12樓B室進度'))
    assert '對唔上' in answer(turn(client, '個案999999進度'))
    assert len(cases.list()['items']) == 1


def test_progress_prompt_accepts_next_turn_spoken_number(estate):
    from edge_hub.resident_cases import PROGRESS_PROMPT
    client, _, _, _ = estate
    answer(turn(client, 'A座十二樓B室水喉漏水', submission_id='8'*32))
    prompt = answer(turn(client, '想查個案進度'))
    assert prompt == PROGRESS_PROMPT
    result = answer(turn(client, '一零零零零一', [{'role': 'user', 'content': '想查個案進度'}, {'role': 'assistant', 'content': prompt}]))
    assert '個案 1' in result


def test_missing_location_can_be_reasked_without_losing_report(estate):
    client, cases, _, _ = estate
    first = '水喉漏水'
    prompt = answer(turn(client, first, submission_id='9'*32))
    history = [{'role': 'user', 'content': first}, {'role': 'assistant', 'content': prompt}]
    repeated = answer(turn(client, '等陣先', history, submission_id='a'*32))
    assert '位置可以遲啲再講' in repeated and not cases.list()['items']
    history += [{'role': 'user', 'content': '等陣先'}, {'role': 'assistant', 'content': repeated}]
    answer(turn(client, 'B座十樓C室', history, submission_id='b'*32))
    row = cases.list()['items'][0]
    assert first in row['message'] and row['unit'] == 'B座10樓C室'


def test_actual_estate_facts_answer_directly_unknown_query_really_goes_to_staff(estate):
    client, cases, facts, _ = estate
    facts.save_knowledge('f'*32, KnowledgeEdit(
        title='合成辦公時間', keywords=['辦公時間'], answer='合成測試：九點開始', expected_revision=0))
    assert '九點' in answer(turn(client, '辦公時間', submission_id='c'*32))
    assert not cases.list()['items']
    assert '管理工作台' in answer(turn(client, '停車收費幾多？', submission_id='d'*32))
    assert cases.list()['items'][0]['team'] == '管理處跟進'


@pytest.mark.parametrize('text', ['如果A座大堂漏水應該點做？', '我今日好唔開心，想有人聽我講', '唔好跟進大堂垃圾，我只係舉例', '有冇人投訴過噪音？', '今日返工好攰，想搵人傾吓'])
def test_hypothetical_negation_and_emotions_do_not_become_automatic_cases(estate, text):
    client, cases, _, _ = estate
    answer(turn(client, text, submission_id='e'*32))
    assert not cases.list()['items']


def test_routing_uses_real_queues_without_claiming_someone_has_arrived(estate):
    client, cases, _, _ = estate
    for index, (message, team) in enumerate([('B座大堂有垃圾', '清潔跟進'), ('B座大堂有煙味', '保安緊急跟進'), ('B座半夜一直嘈', '保安跟進')]):
        result = answer(turn(client, message, submission_id=f'{index+30:032x}'))
        assert team in result and '已有人到場' not in result
    assert len(cases.list()['items']) == 3


def test_explicit_memory_is_not_mistaken_for_a_report_or_progress_query(estate):
    client, cases, facts, _ = estate
    assert '記住咗' in answer(turn(client, '記住：我之前A座12樓B室漏水，個案100001', profile='合成居民', submission_id='f'*32))
    assert not cases.list()['items'] and len(facts.memories('合成居民')) == 1


def test_declined_estate_query_does_not_create_case(estate):
    client, cases, _, _ = estate
    answer(turn(client, '唔好幫我問管理處電話，我只係舉例', submission_id='a'*32))
    assert not cases.list()['items']


def test_how_to_estate_question_is_followed_up_without_a_magic_phrase(estate):
    client, cases, _, _ = estate
    assert '管理工作台' in answer(turn(client, '請問會所點樣預約？', submission_id='b'*32))
    assert len(cases.list()['items']) == 1


def test_care_listens_without_offer_and_only_explicit_contact_request_asks_unit(estate):
    from edge_hub.resident_care import CARE_LOCATION, CARE_OFFER
    client, cases, _, calls = estate
    first = '最近壓力好大，覺得好孤單'
    offered = answer(turn(client, first, submission_id='1'*32))
    assert CARE_OFFER not in offered and '單位' not in offered and not cases.list()['items']
    assert not calls
    history = [{'role': 'user', 'content': first}, {'role': 'assistant', 'content': offered}]
    assert answer(turn(client, '請幫我安排管理人員主動聯絡我', history, submission_id='2'*32)) == CARE_LOCATION
    assert not cases.list()['items']
    history += [{'role': 'user', 'content': '請幫我安排管理人員主動聯絡我'}, {'role': 'assistant', 'content': CARE_LOCATION}]
    result = answer(turn(client, 'A座十二樓B室', history, submission_id='3'*32))
    assert '主動聯絡' in result and '編號 1' in result
    row = cases.list()['items'][0]
    assert row['kind'] == 'human_support' and row['unit'] == 'A座12樓B室'
    assert first in row['message'] and '居民已在對話同意' in row['message']
    answer(turn(client, 'A座十二樓B室', history, submission_id='3'*32))
    assert len(cases.list()['items']) == 1


@pytest.mark.parametrize('reply_text', ['唔使，陪我傾吓就得', '好唔開心', '我仲未諗好', '我想你陪我傾'])
def test_care_declined_or_ambiguous_answer_does_not_ask_unit_or_make_case(estate, reply_text):
    from edge_hub.resident_care import CARE_LOCATION, CARE_OFFER
    client, cases, _, _ = estate
    history = [{'role': 'user', 'content': '我覺得好孤單'}, {'role': 'assistant', 'content': '我想了解多啲。'+CARE_OFFER}]
    result = answer(turn(client, reply_text, history, submission_id='4'*32))
    assert CARE_LOCATION not in result and not cases.list()['items']


def test_care_does_not_repeat_offer_and_can_cancel_after_agreeing(estate):
    from edge_hub.resident_care import CARE_LOCATION, CARE_OFFER
    client, cases, _, _ = estate
    history = [{'role': 'user', 'content': '最近好心煩'}, {'role': 'assistant', 'content': '我聽到。'+CARE_OFFER},
               {'role': 'user', 'content': '唔使'}, {'role': 'assistant', 'content': '我陪你傾。'}]
    assert CARE_OFFER not in answer(turn(client, '依然好心煩', history, submission_id='5'*32))
    history = [{'role': 'user', 'content': '好'}, {'role': 'assistant', 'content': CARE_LOCATION}]
    assert '暫時唔安排' in answer(turn(client, '取消', history, submission_id='6'*32))
    assert not cases.list()['items']


def test_care_stream_listens_without_forcing_a_question_complete_protocol(estate):
    from edge_hub.resident_care import CARE_OFFER
    client, cases, _, calls = estate
    response = turn(client, '最近壓力很大，覺得好孤單', stream=True)
    raw = response.text
    packets = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: {')]
    content = ''.join(packet['choices'][0]['delta'].get('content', '') for packet in packets)
    assert CARE_OFFER not in content and content.count('？') == 0
    assert '孤單' in content and '委屈' not in content and '唔係怪事' not in content
    assert len({packet['id'] for packet in packets}) == 1 and raw.count('[DONE]') == 1
    assert not cases.list()['items'] and not calls


def test_ongoing_care_guidance_does_not_silently_disable_chosen_cloud_model(estate):
    client, cases, _, calls = estate
    history = [{'role': 'user', 'content': '最近返工壓力有啲大'},
               {'role': 'assistant', 'content': '你慢慢講，我會用心聽。'}]
    answer(turn(client, '仲係好心煩，最介意成日俾人打斷', history))
    assert len(calls) == 1 and '繼續承接' in calls[0]['_service_context']
    assert not calls[0].get('_local_only')
    assert not cases.list()['items']


def test_care_with_named_memory_still_keeps_local_only_routing(estate):
    client, cases, _, calls = estate
    history = [{'role': 'user', 'content': '最近返工壓力有啲大'},
               {'role': 'assistant', 'content': '你慢慢講，我會用心聽。'}]
    answer(turn(client, '仲係好心煩，最介意成日俾人打斷', history, profile='公開測試街坊'))
    assert len(calls) == 1 and calls[0]['_local_only'] is True
    assert not cases.list()['items']


@pytest.mark.parametrize('text', ['點解佢成日打斷我？', '點解我咁冇用？', '為什麼他總是不聽我說話？'])
def test_personal_reflection_goes_to_conversation_not_automatic_search(estate, monkeypatch, text):
    client, cases, _, calls = estate
    async def search(*args, **kwargs):
        pytest.fail('Personal feelings must not trigger an unrequested web search')
    monkeypatch.setattr('edge_hub.estate_services.ResidentServices.search', search)
    answer(turn(client, text))
    assert len(calls) == 1
    assert not cases.list()['items']


def test_personal_reflection_filter_keeps_public_facts_and_explicit_search(estate, monkeypatch):
    from edge_hub.estate_services import public_information_query
    client, _, _, _ = estate
    assert public_information_query('點解天空係藍色？')
    assert public_information_query('點解我部電腦開唔到機？')
    searched = []
    async def search(self, query):
        searched.append(query)
        return {'answer': '公開測試來源'}
    monkeypatch.setattr('edge_hub.estate_services.ResidentServices.search', search)
    answer(turn(client, '上網查點解佢成日打斷我'))
    assert searched == ['點解佢成日打斷我']


def test_hypothetical_care_question_does_not_assume_resident_is_distressed(estate):
    from edge_hub.resident_care import CARE_OFFER
    client, cases, _, _ = estate
    assert CARE_OFFER not in answer(turn(client, '如果有人覺得孤單，可以點幫佢？'))
    assert not cases.list()['items']


@pytest.mark.parametrize('consent', ['我想你幫我', '需要你幫手', '係呀', '麻烦你'])
def test_care_accepts_natural_cantonese_and_mandarin_agreement(estate, consent):
    from edge_hub.resident_care import CARE_LOCATION, CARE_OFFER
    client, cases, _, _ = estate
    history = [{'role': 'user', 'content': '最近覺得孤單'}, {'role': 'assistant', 'content': '我聽住。'+CARE_OFFER}]
    assert answer(turn(client, consent, history)) == CARE_LOCATION
    assert not cases.list()['items']


def test_actual_voice_status_reports_runtime_not_just_selected_setting(estate, monkeypatch):
    from edge_hub import estate_services
    client = estate[0]
    def get(url, **kwargs):
        assert url == 'http://127.0.0.1:8765/health'
        return httpx.Response(200, request=httpx.Request('GET', url), json={
            'tts_engine': 'gemini-cantonese-hksoft', 'tts_cloud_cooldown': False,
            'tts_last_resident': {'engine': 'vits-cantonese', 'requested_voice': 'resident-yue', 'at_ms': 123},
            'tts_last': {'engine': 'gemini-cantonese-leda'},
            'other_private_field': 'not for management'})
    monkeypatch.setattr(estate_services.httpx, 'get', get)
    response = client.get('/api/v1/service-desk/voice-status')
    assert response.json() == {'available': True, 'engine': 'vits-cantonese', 'requested_voice': 'resident-yue', 'at_ms': 123, 'cooldown': False}


def test_actual_voice_status_marks_unreachable_service(estate, monkeypatch):
    from edge_hub import estate_services
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError('synthetic unavailable')
    monkeypatch.setattr(estate_services.httpx, 'get', unavailable)
    assert estate[0].get('/api/v1/service-desk/voice-status').json() == {'available': False}


def test_social_opening_does_not_invent_staff_or_estate_activities(estate):
    client, cases, _facts, calls = estate
    first = answer(turn(client, '你好呀，請用廣東話同我簡短打個招呼。'))
    assert '屋苑服務台' in first and '陳小姐' not in first
    second = answer(turn(client, '我哋可以傾啲咩日常話題呀？'))
    assert '興趣' in second and '屋苑有' not in second
    assert calls == []
    assert not cases.list()['items']


def test_social_opening_never_swallows_a_report_or_continued_question():
    from edge_hub.resident_inference import social_opening
    for text in ('你好，我屋企漏水', '我想講今日發生嘅事', '早晨，個案100001進度如何', '我哋可以傾啲咩日常話題？我好孤單'):
        assert social_opening(text) is None


def test_normal_conversation_does_not_repeat_residence_or_service_questions(estate):
    client, cases, _, calls = estate
    first = answer(turn(client, '最近有啲唔開心'))
    assert '聯絡' not in first and '單位' not in first and '想點幫' not in first
    history = [{'role': 'user', 'content': '最近有啲唔開心'}, {'role': 'assistant', 'content': first}]
    answer(turn(client, '我覺得仲有啲心煩，想講吓今日發生嘅事', history))
    assert calls and '唔問住址' in calls[-1]['_service_context']
    assert not cases.list()['items']


def test_contact_location_is_not_repeated_when_resident_changes_subject(estate):
    from edge_hub.resident_care import CARE_LOCATION
    client, cases, _, calls = estate
    history = [{'role': 'user', 'content': '請安排管理人員聯絡我'}, {'role': 'assistant', 'content': CARE_LOCATION}]
    answer(turn(client, '我想先講吓今日發生嘅事', history))
    assert calls and '唔好再追問' in calls[-1]['_service_context']
    assert not cases.list()['items']


def test_public_information_is_searched_without_a_magic_phrase_and_only_current_question(estate, monkeypatch):
    from edge_hub.estate_services import ResidentServices
    client, cases, _, calls = estate
    searched = []
    async def search(self, query):
        searched.append(query)
        return {'context': '已搜尋的公開來源：https://example.org/official'}
    monkeypatch.setattr(ResidentServices, 'search', search)
    question = '香港太空館嘅官方網站係咩？'
    answer(turn(client, question, [{'role': 'user', 'content': '我叫測試稱呼，剛才講私人心事'}], profile='測試稱呼'))
    assert searched == [question]
    assert 'https://example.org/official' in calls[-1]['_service_context']
    assert not cases.list()['items']


@pytest.mark.parametrize('question', ['香港中央圖書館開放時間', '你知唔知香港太空館幾點開門？', '香港有冇舒緩壓力嘅支援服務？'])
def test_public_queries_without_old_keywords_are_searched_not_mistaken_for_personal_distress(estate, monkeypatch, question):
    client, cases, _, calls = estate
    searched = []
    async def search(self, query):
        searched.append(query)
        return {'context': '實際公開來源：https://example.org/official', 'search_status': 'web'}
    monkeypatch.setattr(ResidentServices, 'search', search)
    response = turn(client, question)
    assert response.status_code == 200 and response.headers['X-Resident-Search'] == 'web'
    assert searched == [question] and '_service_context' in calls[-1]
    assert not cases.list()['items']


def test_native_airi_plan_uses_persona_and_real_context_without_choosing_another_model(estate, monkeypatch):
    client, cases, _, calls = estate
    async def search(self, query):
        return {'context': '公開來源：https://example.org/official', 'search_status': 'web'}
    monkeypatch.setattr(ResidentServices, 'search', search)
    response = turn(client, '香港圖書館開放時間', native_settings=True, airi_system_prompt='AIRI內設定的測試角色')
    plan = response.json()
    assert plan['object'] == 'resident.plan'
    assert 'AIRI內設定的測試角色' in plan['system_prompt'] and 'https://example.org/official' in plan['system_prompt']
    assert plan['messages'][-1]['content'] == '香港圖書館開放時間'
    assert response.headers['X-Resident-Search'] == 'web'
    assert not calls and not cases.list()['items']


def test_native_airi_explicit_memory_context_stays_on_existing_local_path(estate):
    client, _, facts, calls = estate
    facts.remember('測試街坊', '鍾意飲淡茶')
    response = turn(client, '今日想飲淡茶', native_settings=True, profile='測試街坊')
    assert response.status_code == 200 and response.json().get('object') != 'resident.plan'
    assert calls[-1]['_local_only'] and '淡茶' in calls[-1]['_service_context']


def test_native_airi_greeting_uses_selected_character_instead_of_the_legacy_fixed_greeting(estate):
    client, _, _, calls = estate
    plan = turn(client, '你好', native_settings=True, airi_system_prompt='角色叫測試小慧').json()
    assert plan['object'] == 'resident.plan' and '測試小慧' in plan['system_prompt']
    assert not calls


def test_native_airi_ordinary_distress_is_answered_by_selected_persona_not_fixed_reflection(estate):
    client, cases, _, calls = estate
    plan = turn(client, '今日返工壓力好大', native_settings=True, airi_system_prompt='親切溫柔的測試角色').json()
    assert plan['object'] == 'resident.plan'
    assert '親切溫柔' in plan['system_prompt'] and '先專心聽' in plan['system_prompt']
    assert not calls and not cases.list()['items']


@pytest.mark.parametrize('text', ['我覺得孤單，可以點樣幫我？', '你覺得我今日過成點？', '我住A座十樓B室，有咩資料？', '本屋苑最新活動係咩？', '管理處電話係咩？'])
def test_private_or_internal_questions_are_not_automatic_web_queries(text):
    from edge_hub.estate_services import public_information_query
    assert not public_information_query(text)


def test_known_estate_answer_precedes_automatic_public_search(estate, monkeypatch):
    from edge_hub.estate_services import ResidentServices
    client, _, facts, _ = estate
    facts.save_knowledge('e'*32, KnowledgeEdit(title='測試資料', keywords=['圖書館開放時間'], answer='管理員確認的測試答案', expected_revision=0))
    async def search(self, query):
        pytest.fail('Known internal answer must not consume external quota')
    monkeypatch.setattr(ResidentServices, 'search', search)
    assert '管理員確認' in answer(turn(client, '圖書館開放時間資料'))


def test_automatic_search_failure_is_honest_and_creates_no_case(estate, monkeypatch):
    from edge_hub.estate_services import ResidentServices
    client, cases, _, _ = estate
    async def search(self, query):
        raise httpx.ConnectError('synthetic network failure')
    monkeypatch.setattr(ResidentServices, 'search', search)
    result = answer(turn(client, '香港太空館官方網站係咩？'))
    assert '未能完成' in result and '唔會當作已經查到' in result
    assert not cases.list()['items']
