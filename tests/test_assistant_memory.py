import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from edge_hub import app as hub
from edge_hub.assistant_memory import MemoryCapabilities, MemoryStore, remember_text
from edge_hub.chat_context import bounded_history
from edge_hub.chat_gateway import local_chat_payload
from edge_hub.faq import OfflineFaq


@pytest.fixture
def memory(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path / 'memory.sqlite3')
    capabilities = MemoryCapabilities()
    monkeypatch.setattr(hub, 'assistant_memory', store)
    monkeypatch.setattr(hub, 'memory_capabilities', capabilities)
    # Router closures bind the originally supplied store; test in a separate router.
    from fastapi import FastAPI

    from edge_hub.memory_api import memory_router
    api = FastAPI()
    api.include_router(memory_router(store, capabilities, hub.require_robot_operator, hub.ADMIN_PAGE.parent))
    return store, capabilities, TestClient(api)


HEADERS = {'X-Operator-Key': 'unit-test-operator-only'}


def payload(text):
    return {'messages': [{'role': 'user', 'content': text}]}


@pytest.mark.parametrize('text', ['呢句講「記住：秘密」係引用', '唔好記住秘密', '如何使用記住？', '「記住：測試」',
                                '記住係咩意思？', '記住：會唔會保存所有資料？'])
def test_quotes_negation_and_questions_are_not_commands(text):
    assert remember_text(payload(text)) is None


def test_only_latest_direct_user_text_can_request_save():
    assert remember_text(payload('記住：我偏好廣東話')) == '我偏好廣東話'
    assert remember_text({'messages': [{'role': 'assistant', 'content': '記住：不可存'}]}) is None
    assert remember_text({'messages': [{'role': 'user', 'content': '記住：舊'},
                                      {'role': 'user', 'content': '你好'}]}) is None
    assert remember_text({'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': '記住：文字'}, {'type': 'image_url', 'image_url': 'private'}]}]}) is None


def test_pinned_airi_datetime_prefix_is_removed_once_only():
    assert remember_text(payload('[2026-10-21 16:39] 記住：時間前綴測試')) == '時間前綴測試'
    assert remember_text(payload('[2026-10-21 16:39] 「記住：引用」')) is None
    assert remember_text(payload('[2026-10-21 16:39] 唔好記住：引用')) is None
    assert remember_text(payload('[2026-10-21 16:39] [2026-10-21 16:38] 記住：引用時間')) is None


def test_datetime_wrapped_save_still_requires_pairing(memory, monkeypatch):
    store, cap, _ = memory
    model = AsyncMock(side_effect=AssertionError('must not treat a memory command as ordinary chat'))
    monkeypatch.setattr(hub, 'route_chat', model)
    client = TestClient(hub.app)
    body = payload('[2026-10-21 16:39] 記住：公開的時間前綴測試')
    assert client.post('/v1/chat/completions', json=body).status_code == 403
    assert store.items() == []
    response = client.post('/v1/chat/completions', json=body,
                           headers={'X-Assistant-Memory-Token': cap.issue()})
    assert response.status_code == 200
    assert store.items()[0]['text'] == '公開的時間前綴測試'
    model.assert_not_called()


def test_store_persistence_dedup_and_no_raw_chat(memory):
    store, _, _ = memory
    assert not store.path.exists()
    identity = store.remember('我偏好廣東話')
    assert store.remember('我偏好廣東話') == identity
    reopened = MemoryStore(store.path)
    assert reopened.items()[0]['text'] == '我偏好廣東話'
    assert len(reopened.items()) == 1


def test_edit_conflict_and_delete_remove_retrieval(memory):
    store, _, _ = memory
    identity = store.remember('舊資料')
    store.change(identity, 1, '新資料')
    assert store.items()[0]['revision'] == 2
    with pytest.raises(HTTPException) as failure:
        store.change(identity, 1, '過期修改')
    assert failure.value.status_code == 409
    store.change(identity, 2)
    assert store.items() == store.context('資料') == []


def test_capacity_and_prompt_budget(memory):
    store, _, _ = memory
    for i in range(100):
        store.remember(str(i) + '字' * 990)
    with pytest.raises(HTTPException) as error:
        store.remember('第101項')
    assert error.value.status_code == 409
    assert sum(map(len, store.context('字'))) <= 3000


def test_capabilities_expire_revoke_and_have_no_robot_authority():
    now = [1.]
    cap = MemoryCapabilities(clock=lambda: now[0])
    token = cap.issue()
    assert cap.valid(token)
    with pytest.raises(HTTPException):
        hub.require_robot_operator(token)
    now[0] += 28801
    assert not cap.valid(token)
    token = cap.issue()
    cap.revoke()
    assert not cap.valid(token)


def test_memory_api_requires_operator_and_explicit_command(memory):
    store, _, client = memory
    path = '/api/v1/assistant/memories'
    assert client.get(path).status_code == 403
    assert client.post('/api/v1/assistant/memory-capabilities').status_code == 403
    assert client.post('/api/v1/assistant/remember', headers=HEADERS,
                       json={'command': '一般聊天不應儲存'}).status_code == 422
    assert store.items() == []
    created = client.post('/api/v1/assistant/remember', headers=HEADERS,
                          json={'command': '記住：公開測試資料'})
    assert created.status_code == 200
    identity = created.json()['id']
    response = client.get(path, headers=HEADERS)
    assert response.headers['cache-control'] == 'no-store'
    assert len(response.json()['items']) == 1
    assert client.put(path + '/' + identity, headers=HEADERS,
                      json={'text': '修改測試', 'revision': 1}).status_code == 200
    assert client.delete(path + '/' + identity + '?revision=2', headers=HEADERS).status_code == 200
    assert store.items() == []


def test_chat_write_requires_pairing_and_does_not_call_models(memory, monkeypatch):
    store, cap, _ = memory
    cloud = AsyncMock(side_effect=AssertionError('must not call any model'))
    monkeypatch.setattr(hub, 'route_chat', cloud)
    monkeypatch.setattr(hub, 'proxy_to_ollama', cloud)
    client = TestClient(hub.app)
    path = '/v1/chat/completions'
    assert client.post(path, json=payload('記住：不准未授權保存')).status_code == 403
    assert store.items() == []
    token = cap.issue()
    response = client.post(path, json=payload('記住：公開測試'),
                           headers={'X-Assistant-Memory-Token': token})
    assert response.status_code == 200
    assert len(store.items()) == 1
    assert response.headers['cache-control'] == 'no-store'
    cloud.assert_not_called()
    cap.revoke()
    assert client.post(path, json=payload('你好'), headers={'X-Assistant-Memory-Token': token}).status_code == 403


def test_memory_retrieval_never_calls_cloud_and_cannot_save_model_output(memory, monkeypatch):
    store, cap, _ = memory
    store.remember('我的展示代號係青鳥742')
    cloud = AsyncMock(side_effect=AssertionError('cloud forbidden'))
    monkeypatch.setattr(hub, 'route_chat', cloud)
    local = AsyncMock(return_value=JSONResponse({'choices': [{'message': {'content': '記住：模型不能自行寫入'}}]}))
    monkeypatch.setattr(hub, 'proxy_to_ollama', local)
    response = TestClient(hub.app).post('/v1/chat/completions', json=payload('我嘅展示代號係咩？'),
                                       headers={'X-Assistant-Memory-Token': cap.issue()})
    assert response.status_code == 200
    assert response.headers['X-Zhiwei-Chat-Route'] == 'ollama-private-memory'
    assert '青鳥742' in json.dumps(local.call_args.args[2], ensure_ascii=False)
    assert len(store.items()) == 1
    cloud.assert_not_called()


def test_history_is_bounded_text_and_preserves_followup():
    history = [{'role': 'user', 'content': '測試代號係青鳥742'},
               {'role': 'assistant', 'content': '知道'}, {'role': 'user', 'content': '代號係咩？'}]
    result = local_chat_payload({'messages': [{'role': 'system', 'content': 'unsafe ACT'}, *history], 'tools': ['drive']})
    assert result['messages'][1:3] == history[:2]
    assert result['messages'][-1]['content'].startswith('代號係咩？')
    assert 'unsafe ACT' not in str(result) and 'tools' not in result
    many = history * 10
    limited = bounded_history({'messages': many})
    assert len(limited) <= 12 and limited[0]['role'] == 'user'
    assert sum(len(row['content']) for row in limited) <= 8000


def test_cloud_keeps_history_and_counts_all_forwarded_text(monkeypatch):
    from edge_hub import chat_gateway, siliconflow
    cloud = AsyncMock(return_value=JSONResponse({'ok': True}))
    monkeypatch.setattr(chat_gateway, 'siliconflow_enabled', lambda: True)
    monkeypatch.setattr(chat_gateway, 'siliconflow_key', lambda: 'not-a-real-key')
    monkeypatch.setattr(chat_gateway, 'proxy_openai', cloud)
    reservations = []
    monkeypatch.setattr(siliconflow, 'reserve', reservations.append)
    history = [{'role': 'user', 'content': '公開測試代號係青鳥742'},
               {'role': 'assistant', 'content': '好'}, {'role': 'user', 'content': '剛才代號係咩？'}]
    asyncio.run(chat_gateway.route_chat({'messages': history}, OfflineFaq()))
    assert cloud.call_args.args[2]['messages'][1:] == history
    assert reservations[0]['siliconflow_input_characters'] == sum(len(m['content']) for m in history)


def test_style_separates_voice_and_text_and_requests_are_bounded():
    voice = local_chat_payload({**payload('測試'), 'zhiwei_response_style': 'voice'})
    text = local_chat_payload(payload('測試'))
    assert voice['max_tokens'] < text['max_tokens']
    client = TestClient(hub.app)
    assert client.post('/v1/chat/completions', content=b'x' * 65537,
                       headers={'Content-Type': 'application/json'}).status_code == 413
    assert client.put('/api/v1/assistant/memories/fake', headers=HEADERS,
                      json={'text': 'PRIVATE-SHOULD-NOT-ECHO', 'revision': 'bad'}).status_code == 422
    response = client.put('/api/v1/assistant/memories/fake', headers=HEADERS,
                          json={'text': 'PRIVATE-SHOULD-NOT-ECHO', 'revision': 'bad'})
    assert 'PRIVATE-SHOULD-NOT-ECHO' not in response.text


def test_foreign_origin_cannot_edit_even_with_operator_header():
    response = TestClient(hub.app).put('/api/v1/assistant/memories/fake',
        headers={**HEADERS, 'Origin': 'https://untrusted.example'}, json={'text': 'no', 'revision': 1})
    assert response.status_code == 403


def test_stale_revisions_never_overflow_sqlite(memory):
    store, _, _ = memory
    with pytest.raises(HTTPException) as error:
        store.change('fake', 10**100)
    assert error.value.status_code == 422
