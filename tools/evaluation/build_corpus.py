"""Versioned fictional multi-turn intent cases; generates Promptfoo's zero-API suite."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAMILIES = [
    ('sorting', ['垃圾應該點樣分類？', '膠樽要唔要除蓋？', '多謝你，我明白喇。'], 0, {}),
    ('social', ['今日行咗陣街。', '見到啲花好靚。', '同你分享下啫，冇嘢要跟進。'], 0, {}),
    ('unit-late', ['我屋企水喉漏水，想搵人處理。', '我係一樓一室嘅住戶。', '補充頭先件事，已經漏咗兩日。'], 1, {'unit': '1樓1室', 'contains': '兩日'}),
    ('unit-first', ['我係一樓一室嘅住戶。', '走廊好多垃圾，想搵人清理。', '補充頭先件事，係門口嗰堆垃圾。'], 1, {'unit': '1樓1室', 'last_kind': 'litter'}),
    ('information-interruption', ['我屋企水喉漏水，請跟進。', '垃圾應該點樣分類？', '補充頭先漏水嗰件事，地下愈來愈濕。'], 1, {'last_kind': 'water', 'contains': '愈來愈濕'}),
    ('different-issue', ['我屋企水喉漏水，請跟進。', '另外一件事，大堂升降機壞咗。', '我係一樓一室嘅住戶。'], 2, {'unit': '1樓1室', 'last_kind': 'general'}),
    ('escalation', ['我屋企水喉漏水，請跟進。', '我係一樓一室嘅住戶。', '補充頭先漏水嗰件事，水滴到電線，仲有火花。'], 1, {'unit': '1樓1室', 'last_kind': 'hazard'}),
    ('pressure', ['我最近生活壓力好大，晚晚都瞓唔到。', '我係一樓一室嘅住戶。', '補充頭先件事，已經持續咗兩星期。'], 1, {'unit': '1樓1室', 'last_kind': 'human_support'}),
    ('crisis', ['我有跳樓衝動。', '我係一樓一室嘅住戶。', '想你哋安排管理人員主動聯絡我。'], 1, {'unit': '1樓1室', 'last_kind': 'human_support'}),
    ('decline', ['走廊好多垃圾，想搵人清理。', '暫時唔想職員聯絡我。', '垃圾分類有咩方法？'], 1, {'last_kind': 'litter'}),
    ('hypothetical', ['假設有人見到漏水，應該點做？', '如果有火花會點？', '我只係想了解原理，冇事發生。'], 0, {}),
    ('remember-unit', ['我係一樓一室嘅住戶。', '垃圾應該點樣分類？', '我屋企水喉漏水，請幫手處理。'], 1, {'unit': '1樓1室', 'last_kind': 'water'}),
]


def main():
    scenarios = []
    for name, turns, count, expected in FAMILIES:
        for suffix, prefix in (('plain', ''), ('polite', '唔該，'), ('casual', '係呀，')):
            # Only vary first user delivery; all later context is retained.
            scenarios.append({'id': name + '-' + suffix, 'turns': [prefix + turns[0], *turns[1:]],
                              'case_count': count, **expected})
    destination = ROOT / 'tests/fixtures/cantonese-multiturn.json'
    destination.write_text(json.dumps({'version': 1, 'fictional_only': True,
        'scope': 'multi-turn routing and data handling, not clinical or Gemma empathy evaluation',
        'scenarios': scenarios}, indent=2, ensure_ascii=False), encoding='utf-8')
    tests = []
    for item in scenarios:
        conditions = [f'r.cases.length === {item["case_count"]}', 'r.network_calls === 0']
        if item.get('unit'):
            conditions.append('r.cases.every(c => c.unit.includes(' + json.dumps(item['unit']) + '))')
        if item.get('last_kind'):
            conditions.append('r.cases.at(-1).kind === ' + json.dumps(item['last_kind']))
        if item.get('contains'):
            conditions.append('r.cases[0].message.includes(' + json.dumps(item['contains']) + ')')
        tests.append({'description': item['id'], 'vars': {'turns': json.dumps(item['turns'], ensure_ascii=False)},
                      'assert': [{'type': 'javascript', 'value': ' && '.join(conditions).replace('r.', 'JSON.parse(output).')}]})
    (ROOT / 'tools/evaluation/promptfooconfig.json').write_text(json.dumps({
        'description': '鄰伴：36組虛構三輪廣東話、零模型API', 'prompts': ['{{turns}}'],
        'providers': [{'id': 'python:cantonese_provider.py:call_api', 'label': 'isolated-intake'}],
        'tests': tests, 'evaluateOptions': {'maxConcurrency': 1}}, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'scenarios': len(scenarios), 'turns': sum(len(item['turns']) for item in scenarios)}))


if __name__ == '__main__':
    main()
