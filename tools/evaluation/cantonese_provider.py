"""Promptfoo local provider: real intake code + isolated in-memory stores.

No network/model/voice calls. This evaluates routing/continuity, not Gemma EQ.
Input and outputs contain fictional test material only.
"""
import hashlib
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from edge_hub.resident_crisis import disclosure
from edge_hub.resident_followup import expressed_need
from edge_hub.service_desk import ServiceDeskStore, service_desk_router


def evaluate(turns):
    history, receipts = [], []
    store = ServiceDeskStore(':memory:')
    async def fake_chat(payload):
        return JSONResponse({'choices': [{'message': {'content': '我願意聽你慢慢講。'}}]})
    app = FastAPI()
    app.include_router(service_desk_router(store, lambda _: None, Path(__file__).resolve().parents[2] / 'edge_hub/static', fake_chat))
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12345))
    try:
        for index, text in enumerate(turns):
            history.append({'role': 'user', 'content': text})
            response = client.post('/api/v1/resident/chat', json={'messages': history, 'native_settings': True,
                'session_id': '1'*32, 'submission_id': hashlib.md5(str(index).encode(), usedforsecurity=False).hexdigest(),
                'stream': False})
            response.raise_for_status()
            data = response.json()
            receipt = data.get('followup')
            need = expressed_need(history)
            receipts.append({'case_number': receipt.get('case_number') if receipt else None,
                             'topic': need['topic'] if need else None, 'crisis': disclosure(text)})
            answer = (data['choices'][0]['message']['content'] if 'choices' in data
                      else '我願意聽你慢慢講。')  # Real plan route; model itself is a zero-API fixture.
            history.append({'role': 'assistant', 'content': answer})
        rows = [dict(row) for row in store.db.execute('SELECT case_number,kind,unit,location,message FROM service_cases ORDER BY case_number')]
        return {'turns': receipts, 'cases': rows, 'network_calls': 0, 'quality_scope': 'routing_only_not_model_empathy'}
    finally:
        store.close()
        client.close()


def call_api(prompt, options, context):
    return {'output': json.dumps(evaluate(json.loads(prompt)), ensure_ascii=False), 'tokenUsage': {'total': 0}}


if __name__ == '__main__':
    print(json.dumps(evaluate(json.loads(sys.stdin.read())), ensure_ascii=False))
