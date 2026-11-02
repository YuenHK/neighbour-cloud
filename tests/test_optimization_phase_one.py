import json

import pytest

from edge_hub.estate_services import EstateStore, KnowledgeEdit
from edge_hub.phase_latency import PhaseLatency
from edge_hub.resident_followup import expressed_need


def test_phase_timings_bound_and_do_not_store_content():
    book = PhaseLatency()
    for _ in range(140):
        with book.measure('azure_complete'):
            pass
    with pytest.raises(RuntimeError), book.measure('gemma_response_ready'):
        raise RuntimeError('private synthetic content')
    report = book.snapshot()
    assert report['phases']['azure_complete']['window_samples'] == 128
    assert report['phases']['gemma_response_ready']['failed'] == 1
    assert 'private' not in json.dumps(report)
    with pytest.raises(ValueError), book.measure('private phone number'):
        pass


@pytest.mark.parametrize(('text', 'kind'), [
    ('大堂成地水，幫手處理', 'water'),
    ('我屋企門口有垃圾，幫手清潔', 'litter'),
    ('𨋢壞咗唔開門', 'general'),
    ('我最近晚晚瞓唔到，好辛苦', 'human_support'),
    ('我冇失眠，最近都瞓得好', None),
    ('朋友話佢失眠，我想了解失眠係咩', None),
    ('如果走廊成地水應該點做', None),
    ('唔好通知管理處，我只想傾吓', None),
    ('你好，今日天氣好好', None),
    ('我最近壓力好大，想有職員聯絡我', 'human_support'),
    ('我想了解會所幾點閂', None),
])
def test_cantonese_intake_corpus(text, kind):
    history = [{'role': 'user', 'content': text}]
    before = json.dumps(history, ensure_ascii=False)
    result = expressed_need(history)
    assert (result['kind'] if result else None) == kind
    assert json.dumps(history, ensure_ascii=False) == before


def test_estate_aliases_ambiguity_disabled_and_data_unchanged(tmp_path):
    store = EstateStore(tmp_path/'estate.sqlite3')
    try:
        store.save_knowledge('a'*32, KnowledgeEdit(title='會所時間', keywords=['會所', '開放時間'], answer='晚上十點關閉'))
        assert store.answer('康樂室開到幾點？') == '晚上十點關閉'
        before = store.knowledge()
        store.save_knowledge('b'*32, KnowledgeEdit(title='另一安排', keywords=['會所', '開放時間'], answer='請核對安排'))
        assert store.answer('會所幾點閂？') is None
        store.save_knowledge('b'*32, KnowledgeEdit(title='另一安排', keywords=['會所'], answer='不用', enabled=False, expected_revision=1))
        assert store.answer('會所幾點閂？') == '晚上十點關閉'
        assert store.knowledge()[-1] == before[0]
    finally:
        store.close()


def test_public_retrieval_does_not_answer_wrong_facility_or_missing_price(tmp_path):
    store = EstateStore(tmp_path/'estate.sqlite3')
    try:
        store.save_knowledge('a'*32, KnowledgeEdit(title='停車場時間', keywords=['開放時間'], answer='每天上午九點開放'))
        assert store.answer('會所幾點閂？') is None
        store.save_knowledge('b'*32, KnowledgeEdit(title='泳池規則', keywords=['泳池'], answer='請戴泳帽'))
        assert store.answer('泳池幾錢？') is None
        assert store.answer('泳池開放時間？') is None
        assert store.answer('泳池有乜規則？') == '請戴泳帽'
    finally:
        store.close()
