import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from deploy.cloud.airi_runtime import AiriRuntime
from deploy.cloud.presentation import Presentation, PresentationEdit, install
from edge_hub.estate_services import EstateStore, ResidentServices


def test_native_airi_defaults_match_working_cloud_and_reject_paid_or_secret_routes():
    value = AiriRuntime().model_dump()
    assert value['speech']['voice_id'] == 'zh-HK-HiuMaanNeural'
    assert value['speech']['rate'] == 1 and value['hearing']['auto_send'] is True
    assert value['memory'] == {'long_term_enabled': True, 'idle_seconds': 180,
                               'context_messages': 60, 'context_characters': 16000}
    for bad in ({'consciousness': {'provider': 'paid'}}, {'speech': {'voice_id': 'other'}},
                {'speech': {'apiKey': 'must-not-be-stored'}}, {'memory': {'idle_seconds': 600}}):
        with pytest.raises(ValidationError):
            AiriRuntime(**bad)


def test_module_preferences_survive_reopen_and_older_airi_editor_without_schema_change(tmp_path):
    estate = EstateStore(tmp_path/'estate.sqlite3')
    try:
        install(estate.db)
        before = estate.db.execute('SELECT name,sql FROM sqlite_master ORDER BY name').fetchall()
        p = Presentation(estate)
        current = p.current()
        current['airi']['runtime']['web_search']['enabled'] = False
        current['airi']['runtime']['speech']['rate'] = .9
        current.pop('revision')
        p.save(PresentationEdit(expected_revision=1, **current))
        p = Presentation(estate)
        assert p.runtime()['web_search']['enabled'] is False
        edit = PresentationEdit(expected_revision=2, name='鄰伴', greeting='你好', persona='', background='mint',
                                airi={'stage_model': 'preset-live2d-1'})
        result = p.save(edit)
        assert result['airi']['runtime']['speech']['rate'] == .9
        assert result['airi']['runtime']['web_search']['enabled'] is False
        assert estate.db.execute('SELECT name,sql FROM sqlite_master ORDER BY name').fetchall() == before
    finally:
        estate.close()


def test_airi_pause_stops_actual_search_and_new_memories_without_deleting_existing(tmp_path):
    estate = EstateStore(tmp_path/'estate.sqlite3')
    try:
        estate.remember('公開測試稱呼', '喜歡種花')
        original = estate.memories('公開測試稱呼')
        service = ResidentServices(estate, None)
        preferences = AiriRuntime().model_dump()
        preferences['web_search']['enabled'] = False
        preferences['memory']['long_term_enabled'] = False
        service.runtime_settings = lambda: preferences
        async def check():
            result = await service.search('公開天氣資訊')
            assert result['search_status'] == 'disabled'
            assert not service.search_cache and not service.search_pending
            body = SimpleNamespace(profile='公開測試稱呼')
            reply = await service.resolve(body, [{'role': 'user', 'content': '記住：喜歡散步'}])
            assert '未有新增' in reply['answer']
            assert estate.memories(body.profile) == original
            assert '暫停' in (await service.resolve(body, [{'role': 'user', 'content': '記得我嗎'}]))['answer']
            # Privacy requests still work while new memory use is paused.
            assert '唔會再用' in (await service.resolve(body, [{'role': 'user', 'content': '忘記：喜歡種花'}]))['answer']
            assert estate.memories(body.profile) == []
        asyncio.run(check())
    finally:
        estate.close()
