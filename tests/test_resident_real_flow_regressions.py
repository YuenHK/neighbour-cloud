"""Actual reported Cantonese failures, synthetic local stores and no providers."""
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from edge_hub.resident_cases import unit_reference
from edge_hub.resident_crisis import SAFETY_QUESTION, disclosure
from edge_hub.service_desk import ServiceDeskStore, service_desk_router


@pytest.fixture
def desk(tmp_path):
    store = ServiceDeskStore(tmp_path / 'synthetic.sqlite3')
    calls = []

    async def chat(payload):
        calls.append(payload)
        return JSONResponse({'choices': [{'message': {'content': '公開合成回覆。'}}]})

    app = FastAPI()
    app.include_router(service_desk_router(store, lambda _: None, tmp_path, chat,
                                          resident_request=lambda _: True))
    with TestClient(app, base_url='http://127.0.0.1:8000') as client:
        yield client, store, calls
    store.db.close()


def turn(client, history, text, identity):
    history.append({'role': 'user', 'content': text})
    result = client.post('/api/v1/resident/chat', json={'messages': history,
        'session_id': 'a' * 32, 'submission_id': f'{identity:032x}', 'native_settings': True})
    assert result.status_code == 200
    data = result.json()
    answer = data.get('choices', [{}])[0].get('message', {}).get('content', '公開合成回覆。')
    history.append({'role': 'assistant', 'content': answer})
    return data


@pytest.mark.parametrize('text', ['我係一樓一室嘅住戶', '一樓一室', '我住1樓A室'])
def test_floor_and_flat_do_not_require_an_invented_block(text):
    assert unit_reference(text) in ('1樓1室', '1樓A室')


@pytest.mark.parametrize('text', ['有時我壓力大就想跳樓', '我有呢個跳樓嘅衝動'])
def test_jumping_impulse_uses_crisis_route(text):
    assert disclosure(text)


def test_volunteered_unit_updates_existing_request_and_care_without_new_case(desk):
    client, store, _ = desk
    h = []
    turn(client, h, '我屋企水管漏水，想管理處跟進', 1)
    turn(client, h, '有時我壓力大就想跳樓', 2)
    turn(client, h, '我係一樓一室嘅住戶', 3)
    rows = store.db.execute('SELECT kind,unit,location FROM service_cases').fetchall()
    assert len(rows) == 2
    assert all(row['unit'] == '1樓1室' for row in rows)
    assert {row['kind'] for row in rows} == {'water', 'human_support'}


def test_crisis_case_can_use_contact_volunteered_before_disclosure(desk):
    client, store, _ = desk
    h = []
    turn(client, h, '我係一樓一室嘅住戶，屋企漏水', 1)
    answer = turn(client, h, '我有呢個跳樓嘅衝動', 2)
    assert SAFETY_QUESTION in answer['choices'][0]['message']['content']
    row = store.db.execute("SELECT unit FROM service_cases WHERE kind='human_support'").fetchone()
    assert row['unit'] == '1樓1室'


def test_new_household_case_remembers_unit_volunteered_in_earlier_turn(desk):
    client, store, _ = desk
    history = []
    turn(client, history, '我係一樓一室嘅住戶', 1)
    turn(client, history, '屋企個水管有問題', 2)
    row = store.db.execute('SELECT unit,location FROM service_cases').fetchone()
    assert row['unit'] == '1樓1室'


def test_household_pipe_problem_is_a_real_request_not_invented_tradespeople(desk):
    client, store, calls = desk
    answer = turn(client, [], '屋企個水管有問題', 1)
    assert 'choices' in answer
    text = answer['choices'][0]['message']['content']
    assert '核實' in text and '師傅' in text
    assert not calls
    assert store.db.execute('SELECT COUNT(*) FROM service_cases').fetchone()[0] == 1


def test_crisis_contact_request_never_promises_a_masked_or_invented_phone(desk):
    client, _, calls = desk
    history = []
    turn(client, history, '我有呢個跳樓嘅衝動', 1)
    answer = turn(client, history, '可唔可以畀求助電話我？', 2)
    text = answer['choices'][0]['message']['content']
    assert '999' in text and 'https://www.swd.gov.hk/' in text
    assert '已隱去' not in text and not calls


# Latest operator requirement includes first mild disclosures; this is a
# concern record, not an emergency flag or a medical assessment.
@pytest.mark.parametrize('text', ['我最近有壓力，晚晚瞓唔著。', '我今日有啲唔開心。',
                                 '我有少少唔開心，但想隨便傾吓。', '最近心情唔係幾好。',
                                 '唔知點解成日想喊。', '我好迷惘，冇人聽我講嘢。'])
def test_emotional_concern_enters_dedicated_non_emergency_support(desk, text):
    client, store, _ = desk
    answer = turn(client, [], text, 1)
    assert answer['object'] == 'resident.plan'
    assert '專門關懷流程' in answer['system_prompt']
    row = store.db.execute('SELECT kind,message FROM service_cases').fetchone()
    assert row['kind'] == 'human_support'
    assert not row['message'].startswith('【需即時關懷】')
