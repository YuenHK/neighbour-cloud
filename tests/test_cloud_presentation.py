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
