"""Synthetic estate facts only: paraphrase retrieval must also know when to abstain."""
import pytest

from edge_hub.estate_services import EstateStore, KnowledgeEdit

FACTS = [
    ('泳池開放時間', ['泳池開放時間'], '泳池每日上午七點至晚上九點開放。'),
    ('泳池入場費', ['泳池入場費'], '泳池每次十元。'),
    ('會所開放時間', ['會所開放時間'], '會所每日上午九點至晚上十點開放。'),
    ('訪客停車場收費', ['訪客停車場收費'], '訪客停車場每小時二十元。'),
    ('管理處電話', ['管理處電話'], '管理處聯絡電話是23456789。'),
    ('垃圾房清理時間', ['垃圾收集時間'], '垃圾房每日晚上八點收集垃圾。'),
    ('健身室開放時間', ['健身室開放時間'], '健身室每日上午八點至晚上十點開放。'),
    ('升降機緊急聯絡電話', ['升降機求助電話'], '升降機緊急聯絡電話是22334455。'),
]
POSITIVES = [
    ('我想游水，泳池夜晚開到幾點？', 0), ('泳池幾點可以入場？', 0),
    ('游泳地方幾點閂門？', 0), ('泳池想問營業時間', 0),
    ('泳池入場要幾錢？', 1), ('去泳池一次點計錢？', 1),
    ('康樂室夜晚幾點收？', 2), ('會所而家開放到幾點？', 2),
    ('會所想問開門時間', 2), ('訪客泊車每個鐘幾錢？', 3),
    ('車場訪客點樣收費？', 3), ('訪客停車場一個鐘點計錢？', 3),
    ('有咩電話可以聯絡管理辦事處？', 4), ('管理處可以打邊個電話？', 4),
    ('邊個電話搵到管理處？', 4), ('幾時有人收垃圾？', 5),
    ('垃圾房幾點有人清理？', 5), ('健身房夜晚幾點閂？', 6),
    ('健身室幾時可以入場？', 6), ('架𨋢有事打邊個電話？', 7),
]
NEGATIVES = [
    '垃圾應該點樣分類？', '想知泳池有幾深？', '泳池有冇救生員？',
    '管理處地址喺邊？', '健身室入場費幾錢？', '升降機幾點開放？',
    '網球場幾點閂？', '住戶停車場要幾錢？', '颱風泳池幾點開？',
    '黑雨會所幾點開？', '我想傾吓工作好攰', '我最近壓力好大。',
    '頭先我報咗漏水，想補充位置', '泳池同會所幾點閂？',
    '每小時幾多錢？', '我住A座三樓B室，幫我問隔籬電話。',
]


@pytest.fixture
def facts(tmp_path):
    store = EstateStore(tmp_path/'facts.sqlite3')
    for index, (title, keywords, answer) in enumerate(FACTS):
        store.save_knowledge(f'{index+1:032x}', KnowledgeEdit(title=title, keywords=keywords, answer=answer))
    yield store
    store.close()


@pytest.mark.parametrize(('question', 'expected'), POSITIVES)
def test_paraphrases_return_only_the_saved_verified_answer(facts, question, expected):
    assert facts.answer(question) == FACTS[expected][2]


@pytest.mark.parametrize('question', NEGATIVES)
def test_other_topics_missing_attributes_and_private_requests_are_not_guessed(facts, question):
    assert facts.answer(question) is None


def test_edit_disable_and_external_database_update_invalidate_index(facts):
    import sqlite3
    question = '管理處可以打邊個電話？'
    assert facts.answer(question) == FACTS[4][2]
    edit = KnowledgeEdit(title=FACTS[4][0], keywords=FACTS[4][1], answer='管理處電話是21234567。', expected_revision=1)
    facts.save_knowledge(f'{5:032x}', edit)
    assert facts.answer(question) == edit.answer
    with sqlite3.connect(facts.path) as other:
        other.execute('UPDATE estate_knowledge SET enabled=0 WHERE id=?', (f'{5:032x}',))
    assert facts.answer(question) is None


def test_conflicting_answers_and_condition_specific_hours_do_not_get_arbitrarily_ranked(facts):
    facts.save_knowledge('a'*32, KnowledgeEdit(title='泳池開放時間', keywords=['泳池時間'], answer='泳池每天上午十點開放。'))
    assert facts.answer('泳池幾點可以入場？') is None


def test_query_does_not_change_original_facts_or_index_resident_memories(facts):
    before = facts.knowledge()
    facts.remember('合成居民', '住戶私人查詢時間：泳池幾點開放。')
    assert facts.answer('游泳地方幾點閂門？') == FACTS[0][2]
    assert facts.knowledge() == before
    facts.save_knowledge('b'*32, KnowledgeEdit(title='合成停用資料', keywords=['網球場開放時間'], answer='網球場九點開放。', enabled=False))
    assert facts.answer('網球場幾點閂？') is None
