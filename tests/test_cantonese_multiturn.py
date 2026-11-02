import json
from pathlib import Path

import pytest

from tools.evaluation.cantonese_provider import evaluate

CORPUS = json.loads((Path(__file__).parent / 'fixtures/cantonese-multiturn.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('scenario', CORPUS['scenarios'], ids=lambda item: item['id'])
def test_context_driven_intake_outcomes(scenario):
    result = evaluate(scenario['turns'])
    assert len(result['cases']) == scenario['case_count']
    for row in result['cases']:
        if scenario.get('unit'):
            assert scenario['unit'] in row['unit']
    if scenario.get('last_kind'):
        assert result['cases'][-1]['kind'] == scenario['last_kind']
    if scenario.get('contains'):
        assert scenario['contains'] in result['cases'][0]['message']
    assert result['network_calls'] == 0
