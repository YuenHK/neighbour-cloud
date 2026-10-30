"""Remote SQL must not rely on connection-local PRAGMA data_version."""
import sqlite3

import pytest

from deploy.cloud.libsql_connection import Connection
from edge_hub.estate_services import EstateStore, KnowledgeEdit


class RemoteConnection(sqlite3.Connection):
    def execute(self, sql, *args, **kwargs):
        if 'data_version' in sql.casefold():
            raise sqlite3.OperationalError('unsupported remote pragma')
        return super().execute(sql, *args, **kwargs)


@pytest.fixture
def remote_estate(tmp_path):
    path = tmp_path / 'estate.sqlite3'
    initial = EstateStore(path)
    initial.close()
    store = EstateStore(path, connection_factory=lambda database, **kw:
                        Connection(sqlite3.connect(database, factory=RemoteConnection, **kw), sqlite3.Error),
                        initialize=False)
    yield store
    store.close()


def test_empty_remote_estate_does_not_block_normal_conversation(remote_estate):
    assert remote_estate.answer('你好') is None


def test_remote_cache_observes_external_edits_even_when_metadata_is_unchanged(remote_estate):
    store = remote_estate
    identity = 'a' * 32
    store.save_knowledge(identity, KnowledgeEdit(title='管理處', keywords=['開放時間'], answer='九點'))
    assert store.answer('開放時間') == '九點'
    store.prepare_index()
    first_index = store._facts_index
    assert first_index is not None
    assert store.answer('開放時間') == '九點'
    assert store._facts_index is first_index
    with sqlite3.connect(store.path) as other:
        other.execute('UPDATE estate_knowledge SET answer=? WHERE id=?', ('十點', identity))
    assert store.answer('開放時間') == '十點'
    with sqlite3.connect(store.path) as other:
        other.execute('UPDATE estate_knowledge SET enabled=0 WHERE id=?', (identity,))
    assert store.answer('開放時間') is None


def test_remote_empty_facts_allow_successive_resident_plans_without_cases(remote_estate, tmp_path):
    from pathlib import Path

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from edge_hub.estate_services import ResidentServices
    from edge_hub.service_desk import ServiceDeskStore, service_desk_router

    cases = ServiceDeskStore(tmp_path / 'cases.sqlite3')

    async def no_inference(_payload):
        raise AssertionError('planning must not dispatch a model')

    app = FastAPI()
    app.include_router(service_desk_router(cases, lambda _key: None,
        Path(__file__).resolve().parents[1] / 'edge_hub/static', no_inference,
        ResidentServices(remote_estate, cases)))
    try:
        with TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 1)) as client:
            history = []
            for text in ('你好', '我今日整咗香蕉蛋糕', '頭先講過整咗乜嘢？'):
                history.append({'role': 'user', 'content': text})
                response = client.post('/api/v1/resident/chat', json={
                    'messages': history, 'native_settings': True, 'stream': True,
                    'session_id': 'a' * 32, 'submission_id': 'b' * 32})
                assert response.status_code == 200
                assert response.json()['object'] == 'resident.plan'
                assert response.json()['messages'][-1]['content'] == text
                history.append({'role': 'assistant', 'content': '公開測試回應。'})
            assert cases.db.execute('SELECT COUNT(*) FROM service_cases').fetchone()[0] == 0
    finally:
        cases.close()
