import sqlite3

import pytest
from test_service_desk import desk as isolated_desk

from edge_hub.resident_crisis import (
    CONTACT_QUESTION,
    FAMILY_URL,
    PREFIX,
    SAFETY_QUESTION,
    disclosure,
)


@pytest.fixture
def desk(tmp_path):
    yield from isolated_desk.__wrapped__(tmp_path)


@pytest.mark.parametrize('text', ['我冇自殺念頭', '我不想自殺', '假設我想自殺', '我模擬想自殺嘅居民', '我朋友想自殺', '我只係唔開心', '笑死我'])
def test_not_a_current_direct_disclosure(text):
    assert not disclosure(text)


def talk(client, history, text, session='a'*32):
    history.append({'role': 'user', 'content': text})
    response = client.post('/api/v1/resident/chat', json={'messages': history, 'session_id': session, 'submission_id': 'b'*32})
    assert response.status_code == 200
    answer = response.json()['choices'][0]['message']['content']
    history.append({'role': 'assistant', 'content': answer})
    return answer


def test_support_exchange_records_one_factual_case_and_offers_practical_resources(desk):
    client, store, calls = desk
    history = []
    first = talk(client, history, '我因為生活困難想自殺')
    assert SAFETY_QUESTION in first and '仍待職員接手' in first
    second = talk(client, history, '冇，我依家冇準備做，只係好難受')
    assert '可以先揀一件' in second and SAFETY_QUESTION not in second
    third = talk(client, history, '有咩機構可以幫我處理經濟問題？')
    assert FAMILY_URL in third and '向晴軒' in third and '999' not in third
    fourth = talk(client, history, '我想先放鬆一下')
    assert '雙腳' in fourth and '正常呼吸' in fourth
    rows = store.db.execute('SELECT * FROM service_cases').fetchall()
    assert len(rows) == 1 and rows[0]['message'].startswith(PREFIX)
    assert '居民直接表達' in rows[0]['message'] and '非醫療診斷' in rows[0]['message']
    assert rows[0]['due_at_ms']-rows[0]['created_at_ms'] == 300000
    assert rows[0]['location'] == rows[0]['contact'] == ''
    assert not calls  # No quota, external send or model dependency.


def test_contact_only_after_resident_chooses_outreach_and_keeps_staff_note(desk):
    client, store, _ = desk
    history = []
    talk(client, history, '我唔想活落去')
    offer = talk(client, history, '可以幫我安排管理人員聯絡嗎？')
    assert CONTACT_QUESTION in offer
    store.db.execute("UPDATE service_cases SET note='職員原有跟進',assignee='測試職員'")
    store.db.commit()
    talk(client, history, '我住A座3樓301室')
    row = store.db.execute('SELECT * FROM service_cases').fetchone()
    assert row['unit'].endswith('301室') and row['note'] == '職員原有跟進'
    assert row['assignee'] == '測試職員' and row['revision'] == 2


def test_immediate_danger_precedes_relaxation_and_queue_is_not_emergency_dispatch(desk):
    client, _, _ = desk
    history = []
    talk(client, history, '我想自殺')
    answer = talk(client, history, '有，正準備，想先放鬆')
    assert '999' in answer and '唔等於已召喚救護車' in answer
    assert '三樣' not in answer


def test_new_session_is_separate_and_failed_queue_never_claims_delivery(desk, monkeypatch):
    client, store, _ = desk
    talk(client, [], '我想自殺', session='c'*32)
    talk(client, [], '我想自殺', session='d'*32)
    assert store.db.execute('SELECT COUNT(*) FROM service_cases').fetchone()[0] == 2
    def fail(request):
        raise sqlite3.OperationalError('synthetic_failure')
    monkeypatch.setattr(store, 'create', fail)
    answer = talk(client, [], '我想自殺', session='e'*32)
    assert SAFETY_QUESTION in answer and '未能確認交到' in answer
    assert '已交到' not in answer
