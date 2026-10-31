import sqlite3

import pytest
from fastapi import HTTPException


def test_cloud_presentation_keeps_existing_facts_and_revision(tmp_path):
    from deploy.cloud.presentation import Presentation, PresentationEdit, install
    from edge_hub.estate_services import EstateStore
    estate = EstateStore(tmp_path / 'estate.sqlite3')
    try:
        install(estate.db)
        settings = Presentation(estate)
        before = settings.current()
        assert before['revision'] == 1
        result = settings.save(PresentationEdit(expected_revision=1, name='鄰伴', greeting='你好，慢慢傾。',
            persona='先聽居民講完，再溫柔接話。', background='mint'))
        assert result['revision'] == 2
        with pytest.raises(HTTPException) as failure:
            settings.save(PresentationEdit(expected_revision=1, **{k: v for k, v in result.items() if k != 'revision'}))
        assert failure.value.status_code == 409
        assert 'persona' not in settings.public()
        install(estate.db)  # Recovery preparation does not reset saved preferences.
        assert Presentation(estate).current() == result
        assert estate.db.execute('SELECT COUNT(*) FROM estate_knowledge').fetchone()[0] == 0
    finally:
        estate.close()


def test_missing_or_invalid_presentation_never_makes_implicit_tables(tmp_path):
    from deploy.cloud.presentation import Presentation
    from edge_hub.estate_services import EstateStore
    estate = EstateStore(tmp_path / 'estate.sqlite3')
    try:
        with pytest.raises(sqlite3.Error):
            Presentation(estate)
        assert estate.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='cloud_presentation'").fetchone()[0] == 0
    finally:
        estate.close()


def test_airi_character_and_model_survive_reopen_without_exposing_character_prompt(tmp_path):
    from deploy.cloud.presentation import Presentation, PresentationEdit, install
    from edge_hub.estate_services import EstateStore
    estate = EstateStore(tmp_path / 'estate.sqlite3')
    try:
        install(estate.db)
        settings = Presentation(estate)
        edit = PresentationEdit(expected_revision=1, name='鄰伴', greeting='慢慢傾。',
            persona='', background='mint', airi={
                'stage_model': 'preset-live2d-2', 'scene_background': 'builtin:cozy-tea-corner',
                'card': {'name': '鄰伴', 'description': '熟悉的好鄰居', 'personality': '溫柔自然',
                         'scenario': '屋苑服務', 'system_prompt': '先聽對方說完。'}})
        settings.save(edit)
        reopened = Presentation(estate)
        assert reopened.current()['airi']['card']['personality'] == '溫柔自然'
        assert reopened.public()['airi']['stage_model'] == 'preset-live2d-2'
        assert 'card' not in reopened.public()['airi']
        assert '先聽對方說完。' in reopened.prompt()
        assert reopened.current()['revision'] == 2
        # A still-open older four-field editor must not erase the AIRI profile.
        updated = reopened.save(PresentationEdit(expected_revision=2, name='鄰伴',
            greeting='歡迎返嚟。', persona='', background='mint'))
        assert updated['airi'] == edit.airi.model_dump()
        assert updated['revision'] == 3
    finally:
        estate.close()


@pytest.mark.parametrize('bad', [
    {'stage_model': 'https://unknown.test/private.vrm'},
    {'api_key': 'synthetic-not-a-real-key'},
    {'card': {'name': 'A', 'system_prompt': 'x' * 4001}},
])
def test_airi_settings_reject_unmanaged_provider_secrets_and_oversize_prompt(bad):
    from pydantic import ValidationError

    from deploy.cloud.presentation import PresentationEdit
    with pytest.raises(ValidationError):
        PresentationEdit(expected_revision=1, name='鄰伴', greeting='你好', persona='',
                         background='mint', airi=bad)
