"""Isolated full HTTP intake: short references, supplements, distinct issues and retries."""
import json

import pytest
from test_resident_followup import turn
from test_service_desk import desk as isolated_desk

from edge_hub.resident_cases import progress_query
from edge_hub.service_desk import ResidentCase, ReviewCase, ServiceDeskStore


@pytest.fixture
def desk(tmp_path):
    yield from isolated_desk.__wrapped__(tmp_path)


def history(text):
    return [{'role': 'user', 'content': text}, {'role': 'assistant', 'content': '我記低咗，會交畀職員跟進。'}]


def reply_text(response):
    assert response.status_code == 200
    if 'application/json' in response.headers['content-type']:
        return response.json()['choices'][0]['message']['content']
    assert 'data: [DONE]' in response.text
    return ''.join(json.loads(line[6:])['choices'][0].get('delta', {}).get('content', '')
                   for line in response.text.splitlines() if line.startswith('data: {'))


def test_short_numbers_start_at_one_survive_reopen_and_keep_old_references(tmp_path):
    path = tmp_path/'cases.sqlite3'
    store = ServiceDeskStore(path)
    a = store.create(ResidentCase(submission_id='a'*32, kind='water', message='合成漏水報告', confirmed=True))
    b = store.create(ResidentCase(submission_id='b'*32, kind='litter', message='合成垃圾報告', confirmed=True))
    assert [a['case_number'], b['case_number']] == [1, 2]
    original = tuple(store.db.execute('SELECT * FROM service_cases WHERE id=?', (a['id'],)).fetchone())
    store.close()
    store = ServiceDeskStore(path)
    try:
        assert tuple(store.db.execute('SELECT * FROM service_cases WHERE id=?', (a['id'],)).fetchone()) == original
        assert store.list()['items'][0]['case_number'] == 2
        assert store.progress('1') == store.progress('100001') == store.progress(a['id'])
        for phrase in ('查個案1進度', '我想查一號個案進度', '編號一'):
            assert '個案 1' in progress_query(phrase, [], store)
        prompt = [{'role': 'user', 'content': '查單位進度'},
                  {'role': 'assistant', 'content': '呢個單位有多過一個個案：1；2。想查邊個編號？'}]
        assert '個案 2' in progress_query('二', [*prompt, {'role': 'user', 'content': '二'}], store)
        assert store.create(ResidentCase(submission_id='c'*32, kind='general', message='公開新個案', confirmed=True))['case_number'] == 3
    finally:
        store.close()


def test_supplement_changes_topic_but_updates_original_case_and_staff_notes(desk):
    client, store, _ = desk
    first_text = 'A座走廊水喉漏水，請幫手處理。'
    first = turn(client, first_text).json()['followup']
    row = store.list()['items'][0]
    store.review(first['id'], ReviewCase(expected_revision=row['revision'], status='acknowledged', note='已安排維修'))
    text = '補充頭先漏水嗰件事，水滴到電線，仲有火花。'
    second = turn(client, text, history(first_text), submission='3'*32).json()['followup']
    assert first['id'] == second['id']
    row = store.list()['items'][0]
    assert row['kind'] == 'hazard' and row['team'] == '保安緊急跟進'
    assert row['note'] == '已安排維修' and row['status'] == 'acknowledged'
    assert first_text in row['message'] and text in row['message']
    before_revision = row['revision']
    assert turn(client, text, history(first_text), submission='3'*32).json()['followup']['id'] == first['id']
    assert store.list()['items'][0]['revision'] == before_revision
    assert len(store.list()['items']) == 1


@pytest.mark.parametrize('supplement', ['補充一下，已經兩日，係天花滴落嚟。', '位置喺A座三樓走廊。', '想請管理人員主動聯絡我。'])
def test_details_without_repeating_issue_are_appended(desk, supplement):
    client, store, _ = desk
    text = '我屋企漏水，請幫手。'
    first = turn(client, text).json()['followup']
    followup = turn(client, supplement, history(text), submission='4'*32).json()['followup']
    assert followup['id'] == first['id']
    assert supplement in store.list()['items'][0]['message']
    assert len(store.list()['items']) == 1


@pytest.mark.parametrize('new_text', [
    '另外一件事，B座走廊都漏水，麻煩處理。',
    '另外大堂有一堆垃圾，請安排清理。',
    'B座走廊漏水，請幫手。',
    'A座大堂漏水，請幫手。',
])
def test_new_issue_or_distinct_place_gets_a_new_case(desk, new_text):
    client, store, _ = desk
    text = 'A座走廊水喉漏水，請幫手。'
    first = turn(client, text).json()['followup']
    second = turn(client, new_text, history(text), submission='5'*32).json()['followup']
    assert second['id'] != first['id'] and second['case_number'] == 2
    assert turn(client, new_text, history(text), submission='5'*32).json()['followup']['id'] == second['id']
    assert len(store.list()['items']) == 2


def test_supplement_after_switch_returns_to_referenced_issue(desk):
    client, store, _ = desk
    water = 'A座走廊水喉漏水，請幫手。'
    a = turn(client, water).json()['followup']
    litter = '另外大堂有一堆垃圾，請清理。'
    b = turn(client, litter, history(water), submission='3'*32).json()['followup']
    turns = [*history(water), *history(litter)]
    reply = turn(client, '補充頭先漏水嗰單，已經兩日。', turns, submission='4'*32).json()['followup']
    assert reply['id'] == a['id'] and reply['id'] != b['id']
    assert len(store.list()['items']) == 2


def test_completed_case_retry_never_opens_new_and_actual_new_turn_does(desk):
    client, store, _ = desk
    text = 'A座走廊水喉漏水，請幫手。'
    a = turn(client, text).json()['followup']
    row = store.list()['items'][0]
    store.review(a['id'], ReviewCase(expected_revision=row['revision'], status='resolved', note='已完成'))
    assert turn(client, text).json()['followup']['id'] == a['id']
    b = turn(client, '又漏水，A座走廊水喉再壞咗。', history(text), submission='6'*32).json()['followup']
    assert b['id'] != a['id']
    assert store.list()['counts'] == {'new': 1, 'resolved': 1}


def test_information_after_report_never_updates_or_creates_a_case(desk):
    client, store, _ = desk
    text = 'A座大堂有一堆垃圾，請清理。'
    turn(client, text)
    before = store.list()['items']
    for index, question in enumerate(('垃圾應該點樣分類？', '我屋企啲垃圾應該點樣分類？')):
        response = turn(client, question, history(text), submission=f'{10+index:032x}').json()
        assert 'followup' not in response
    assert store.list()['items'] == before


def test_contact_only_does_not_copy_to_unrelated_issue_description(desk):
    client, store, _ = desk
    a = turn(client, 'A座走廊漏水，請處理。').json()['followup']
    turn(client, '另外大堂有垃圾，請清理。', submission='3'*32)
    text = '補充頭先漏水嗰單，係A座三樓走廊。'
    turn(client, text, submission='4'*32)
    rows = store.list()['items']
    assert text in next(row for row in rows if row['id'] == a['id'])['message']
    assert text not in next(row for row in rows if row['id'] != a['id'])['message']


@pytest.mark.parametrize('text', ['補充個案一，漏咗兩日。', '個案一，我補充一下，漏咗兩日。'])
def test_explicit_short_case_reference_updates_instead_of_becoming_progress_query(desk, text):
    client, store, _ = desk
    a = turn(client, 'A座走廊漏水，請處理。').json()['followup']
    turn(client, '另外大堂有垃圾，請清理。', submission='3'*32)
    result = turn(client, text, submission='4'*32).json()['followup']
    assert result['id'] == a['id']
    assert text in next(row for row in store.list()['items'] if row['id'] == a['id'])['message']


def test_case_and_replay_binding_roll_back_together(desk, monkeypatch):
    client, store, _ = desk
    original = store.record_automatic

    def fail_after_case(*args, **kwargs):
        original(*args, **kwargs)
        import sqlite3
        raise sqlite3.OperationalError('isolated fault after case insert')
    monkeypatch.setattr(store, 'record_automatic', fail_after_case)
    response = turn(client, 'A座走廊漏水，請處理。').json()
    assert response['followup']['delivered'] is False
    assert not store.list()['items']
    assert store.db.execute('SELECT COUNT(*) FROM resident_session_turns').fetchone()[0] == 0
    monkeypatch.setattr(store, 'record_automatic', original)
    assert turn(client, 'A座走廊漏水，請處理。').json()['followup']['case_number'] == 1


def test_reopen_keeps_continuity_and_retry_cannot_change_the_bound_content(desk):
    client, store, _ = desk
    text = 'A座走廊漏水，請處理。'
    a = turn(client, text).json()['followup']
    path = store.db.execute('PRAGMA database_list').fetchone()[2]
    reopened = ServiceDeskStore(path)
    try:
        from edge_hub.resident_threads import replay, session_rows
        assert replay(reopened, '1'*32, '2'*32, quote=text)['id'] == a['id']
        assert session_rows(reopened, '1'*32)[0]['id'] == a['id']
    finally:
        reopened.close()
    result = turn(client, 'B座走廊有另一件事，漏水要處理。').json()
    assert result['followup']['delivered'] is False
    assert len(store.list()['items']) == 1


def test_explicit_new_subject_wins_over_a_reference_to_previous_conversation(desk):
    client, store, _ = desk
    a = turn(client, 'A座走廊漏水，請處理。').json()['followup']
    b = turn(client, '頭先講完漏水，另外一件事，B座水喉都漏水。', submission='3'*32).json()['followup']
    assert a['id'] != b['id'] and len(store.list()['items']) == 2


def test_chinese_ten_and_floor_numbers_are_not_confused(desk):
    client, store, _ = desk
    for index in range(10):
        store.create(ResidentCase(submission_id=f'{index:032x}', kind='water', message='公開合成維修', location='A座3樓B室', confirmed=True))
    result = reply_text(turn(client, '編號十'))
    assert '個案 1、0' in result
    result = reply_text(turn(client, '我住A座3樓B室，查進度'))
    assert '多過一個' in result  # Floor 3 is not treated as case 3.


def test_duration_answer_to_lift_problem_keeps_original_issue(desk):
    client, store, _ = desk
    text = 'A座升降機壞咗，唔開門。'
    a = turn(client, text).json()['followup']
    result = turn(client, '已經壞咗兩日。', history(text), submission='3'*32).json()['followup']
    assert a['id'] == result['id'] and len(store.list()['items']) == 1


def test_explicit_care_escalation_updates_existing_care_report_and_preserves_contact(desk):
    from edge_hub.resident_crisis import CONTACT_QUESTION, PREFIX
    client, store, _ = desk
    text = '我最近壓力好大，日日瞓唔到。'
    a = turn(client, text).json()['followup']
    answer = reply_text(turn(client, '我因為生活困難想自殺', history(text), submission='3'*32))
    assert '你而家有冇已經傷害自己' in answer
    row = store.list()['items'][0]
    assert len(store.list()['items']) == 1 and row['id'] == a['id']
    assert row['message'].startswith(PREFIX) and text in row['message']
    assert row['due_at_ms']-row['created_at_ms'] == 300000
    follow = [*history(text), {'role': 'user', 'content': '我因為生活困難想自殺'},
              {'role': 'assistant', 'content': CONTACT_QUESTION}]
    reply_text(turn(client, '我住A座3樓301室', follow, submission='4'*32))
    assert len(store.list()['items']) == 1 and store.list()['items'][0]['unit'] == 'A座3樓301室'


def test_direct_handoff_outside_keyword_topics_also_binds_supplements(desk):
    client, store, _ = desk
    text = '通知管理處，大堂招牌字模脫落。'
    reply_text(turn(client, text))
    assert len(store.list()['items']) == 1
    original = store.list()['items'][0]
    detail = '補充頭先招牌嗰單，甩咗三日。'
    result = turn(client, detail, history(text), submission='3'*32).json()['followup']
    assert result['id'] == original['id'] and detail in store.list()['items'][0]['message']
    assert len(store.list()['items']) == 1
