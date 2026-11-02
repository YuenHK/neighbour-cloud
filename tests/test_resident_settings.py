import json

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from edge_hub import resident_inference
from edge_hub.resident_models import FAST_MODEL, GEMMA_MODEL
from edge_hub.resident_settings import chat_settings_router


def test_automatic_routing_status_is_read_only_and_authenticated():
    def authorize(key):
        if key != 'synthetic-operator':
            raise HTTPException(403)
    app = FastAPI()
    app.include_router(chat_settings_router(authorize))
    with TestClient(app) as client:
        url = '/api/v1/service-desk/chat-settings'
        assert client.get(url).status_code == 403
        headers = {'X-Operator-Key': 'synthetic-operator'}
        response = client.get(url, headers=headers)
        result = response.json()
        assert result['model'] is None and result['default_model'] == GEMMA_MODEL and result['authority'] == 'airi'
        assert result['fast_backup'] is None and not result['local_backup']
        assert not result['automatic'] and 'options' not in result
        assert response.headers['cache-control'] == 'no-store'
        assert client.put(url, json={'model': FAST_MODEL}, headers=headers).status_code == 405


def test_previous_selection_cannot_override_gemma_policy(tmp_path, monkeypatch):
    path = tmp_path/'runtime.json'
    monkeypatch.setattr(resident_inference, 'CONFIG', path)
    for chosen in (FAST_MODEL, GEMMA_MODEL, 'paid-model'):
        saved = {'mode': 'gemini-free', 'model': 'qwen3:4b-instruct-2507-q4_K_M', 'cloud_model': chosen}
        path.write_text(json.dumps(saved), encoding='utf-8')
        assert resident_inference.configuration()['cloud_model'] == GEMMA_MODEL
        assert json.loads(path.read_text()) == saved
