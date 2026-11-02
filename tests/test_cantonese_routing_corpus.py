import json
from pathlib import Path

import pytest

from edge_hub.estate_services import public_information_query
from edge_hub.resident_cases import progress_query
from edge_hub.resident_crisis import disclosure
from edge_hub.resident_followup import expressed_need
from edge_hub.service_desk import ServiceDeskStore

CORPUS=json.loads((Path(__file__).parent/'fixtures/cantonese-routing.json').read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('example',CORPUS,ids=lambda row:row['id'])
def test_cantonese_gold_routes(example):
    history=[*example.get('history',[]),{'role':'user','content':example['text']}]
    if 'crisis' in example:
        assert disclosure(example['text']) is example['crisis']
    if 'topic' in example:
        result=expressed_need(history)
        if example['topic'] is None:
            assert result is None
        else:
            assert result is not None
            assert (result['topic'],result['kind']) == (example['topic'],example['kind'])
    if 'public_search' in example:
        assert public_information_query(example['text']) is example['public_search']
    if example.get('progress'):
        store=ServiceDeskStore(':memory:')
        try:assert progress_query(example['text'],history,store) is not None
        finally:store.close()


def test_corpus_ids_are_unique_and_contain_context_and_negative_examples():
    assert len({row['id'] for row in CORPUS})==len(CORPUS)
    assert sum(bool(row.get('history')) for row in CORPUS)>=3
    assert sum(row.get('topic','absent') is None for row in CORPUS)>=20
