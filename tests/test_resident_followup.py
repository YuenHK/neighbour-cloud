import sqlite3

import pytest
from test_service_desk import AUTH, PATH
from test_service_desk import desk as isolated_desk

from edge_hub.resident_followup import expressed_need


@pytest.fixture
def desk(tmp_path):
    yield from isolated_desk.__wrapped__(tmp_path)


def turn(client, text, history=None, *, session='1'*32, submission='2'*32):
    return client.post('/api/v1/resident/chat', json={
        'messages': [*(history or []), {'role': 'user', 'content': text}],
        'native_settings': True, 'session_id': session, 'submission_id': submission, 'stream': True})


@pytest.mark.parametrize(('text', 'group', 'kind'), [
    ('我最近生活壓力好大，真係頂唔順。', 'care', 'human_support'),
    ('壓力好大，日日都瞓唔到。', 'care', 'human_support'),
    ('我覺得好孤單，成日冇人理。', 'care', 'human_support'),
    ('我呢排好唔開心，晚晚瞓唔著。', 'care', 'human_support'),
    ('我有抑鬱症，最近想有人支援我。', 'care', 'human_support'),
    ('我屋企漏水，有冇人可以幫手？', 'requests', 'water'),
    ('見到大堂有好多垃圾，想請人清理。', 'requests', 'litter'),
    ('升降機壞咗，唔開門。', 'requests', 'general'),
    ('我想問管理費可唔可以分期。', 'requests', 'general'),
    ('我想申請屋苑車位。', 'requests', 'general'),
    ('我想請管理人員主動聯絡我。', 'requests', 'general'),
    ('我需要社工幫手。', 'care', 'human_support'),
    ('我最近失業，冇錢交租開飯。', 'requests', 'general'),
    ('大堂有人騷擾我，希望保安跟進。', 'requests', 'general'),
    ('我需要幫助，但唔知由邊度開始。', 'requests', 'general'),
])
def test_native_conversation_immediately_reaches_the_right_staff_queue_without_contact(desk, text, group, kind):
    client, store, calls = desk
    response = turn(client, text)
    assert response.status_code == 200
    data = response.json()
    assert data['object'] == 'resident.plan'
    receipt = data['followup']
    assert receipt['delivered'] and receipt['group'] == group
    listed = client.get(PATH+'?group='+group, headers=AUTH).json()
    assert len(listed['items']) == 1 and listed['items'][0]['kind'] == kind
    assert text in listed['items'][0]['message']
    assert listed['items'][0]['intake_mode'] == 'automatic'
    assert listed['items'][0]['id'] == receipt['id']
    assert isinstance(receipt['case_number'], int)
    assert not calls  # Workbench delivery does not depend on a cloud reply/TTS succeeding.
    assert store.db.execute('SELECT COUNT(*) FROM service_cases').fetchone()[0] == 1


def test_repeat_turns_update_one_case_preserve_staff_edits_and_accept_volunteered_contact(desk):
    client, store, _ = desk
    first = turn(client, '我壓力好大，晚晚都瞓唔著。').json()['followup']
    store.db.execute("UPDATE service_cases SET note='原有職員進度',assignee='當值職員'")
    store.db.commit()
    history = [{'role': 'user', 'content': '我壓力好大，晚晚都瞓唔著。'},
               {'role': 'assistant', 'content': '呢段時間捱得辛苦，我聽緊。'}]
    second = turn(client, '我最近焦慮到唔想出門。', history, submission='3'*32).json()['followup']
    assert second['id'] == first['id']
    assert turn(client, '我最近焦慮到唔想出門。', history, submission='3'*32).json()['followup']['id'] == first['id']
    contact = turn(client, '我住A座3樓301室，電話91234567。', history, submission='4'*32).json()['followup']
    assert contact['contact_available'] and contact['id'] == first['id']
    rows = client.get(PATH+'?group=care', headers=AUTH).json()['items']
    assert len(rows) == 1 and rows[0]['contact'] == '91234567'
    assert rows[0]['unit'] == 'A座3樓301室'
    assert rows[0]['note'] == '原有職員進度' and rows[0]['assignee'] == '當值職員'
    assert '晚晚都瞓唔著' in rows[0]['message'] and rows[0]['message'].count('焦慮到') == 1


def test_opt_out_is_respected_and_existing_report_flags_no_outreach(desk):
    client, store, _ = desk
    assert 'followup' not in turn(client, '我壓力好大，但唔好通知管理人員。').json()
    assert not store.list()['items']
    history = [{'role': 'user', 'content': '我壓力好大，但唔好通知管理人員。'},
               {'role': 'assistant', 'content': '我聽緊，唔轉交。'}]
    assert 'followup' not in turn(client, '我仲係覺得好孤單。', history).json()
    turn(client, '請幫我安排管理人員聯絡我，我最近壓力好大。', history)
    receipt = turn(client, '唔好再聯絡我。', submission='4'*32).json()['followup']
    assert receipt['delivered']
    row = store.list(group='care')['items'][0]
    assert row['contact_preference'] == 'declined'


@pytest.mark.parametrize('text', [
    '你好呀，今日天氣幾好。', '我今日食咗個蛋糕，好開心。',
    '抑鬱症係咩？', '焦慮有咩定義？', '如果有人有壓力可以點做？',
    '我朋友有抑鬱症。', '我朋友壓力好大。', '我覺得鄰居有精神病。', '升降機係點樣運作？',
    '我冇壓力，想知壓力係咩。', '我已經冇漏水。',
])
def test_general_chat_information_third_party_labels_and_hypotheticals_are_not_health_assessments(text):
    assert expressed_need([{'role': 'user', 'content': text}]) is None


def test_next_resident_is_separate_and_delivery_failure_never_claims_success(desk, monkeypatch):
    client, store, _ = desk
    a = turn(client, '我最近好孤單。').json()['followup']
    b = turn(client, '我最近好孤單。', session='9'*32).json()['followup']
    assert a['id'] != b['id']
    def fail(request, **kwargs):
        raise sqlite3.OperationalError('synthetic storage failure')
    monkeypatch.setattr(store, 'record_automatic', fail)
    response = turn(client, '我屋企漏水，請幫手。', session='8'*32).json()
    assert response['followup']['delivered'] is False
    assert '未能確認' in response['followup']['notice']
    assert '已交到' not in response['followup']['notice']


def test_unknown_estate_information_reuses_one_staff_request_and_global_badges_include_both_queues(desk):
    client, _, _ = desk
    first = turn(client, '管理處電話係幾多？').json()['followup']
    second = turn(client, '管理處電話係幾多？', submission='5'*32).json()['followup']
    assert first['id'] == second['id']
    turn(client, '我最近壓力好大。', submission='6'*32)
    summary = client.get('/api/v1/service-desk/summary', headers=AUTH).json()
    assert summary['pending_by_group'] == {'care': 1, 'requests': 1}
    assert '壓力' not in str(summary)  # Navigation counters never expose resident messages.


def test_new_need_after_staff_resolution_creates_one_new_case_and_preserves_closed_record(desk):
    client, store, _ = desk
    original = turn(client, '我屋企漏水，幫我處理。').json()['followup']
    store.db.execute("UPDATE service_cases SET status='resolved',note='已完成原有維修' WHERE id=?", (original['id'],))
    store.db.commit()
    next_case = turn(client, '我屋企又漏水，麻煩再幫手。', submission='5'*32).json()['followup']
    assert next_case['id'] != original['id']
    assert turn(client, '我屋企又漏水，麻煩再幫手。', submission='5'*32).json()['followup']['id'] == next_case['id']
    turn(client, '我住B座2樓201室。', submission='6'*32)
    rows = store.list()['items']
    assert len(rows) == 2
    closed = next(row for row in rows if row['id'] == original['id'])
    active = next(row for row in rows if row['id'] == next_case['id'])
    assert closed['status'] == 'resolved' and closed['note'] == '已完成原有維修'
    assert active['unit'] == 'B座2樓201室'


def test_hypothetical_opt_out_and_other_peoples_contact_are_not_attached_to_resident(desk):
    client, store, _ = desk
    turn(client, '我最近壓力好大。')
    turn(client, '如果唔想通知管理人員，可以點做？', submission='5'*32)
    turn(client, '鄰居電話91234567，佢住B座2樓201室。', submission='6'*32)
    row = store.list(group='care')['items'][0]
    assert row['contact_preference'] == 'unknown'
    assert row['unit'] == row['contact'] == ''
