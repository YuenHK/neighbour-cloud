from datetime import UTC, datetime

import pytest

from edge_hub.events import Event, EventStore
from edge_hub.service_desk import ResidentCase, ServiceDeskStore
from edge_hub.workbench_query import validate


def test_case_filters_apply_before_paging_and_keep_short_number_search(tmp_path):
    store = ServiceDeskStore(tmp_path / 'cases.sqlite3')
    try:
        ids = []
        for index in range(63):
            item = store.create(ResidentCase(submission_id=f'{index:032x}', kind='human_support' if index == 62 else 'water',
                message='公開測試：水喉漏水', location='1樓1室', confirmed=True))
            ids.append(item['id'])
        with store.db:
            for index, identity in enumerate(ids):
                store.db.execute('UPDATE service_cases SET created_at_ms=?,updated_at_ms=?,status=? WHERE id=?',
                    (index + 1, 1000 - index, 'resolved' if index < 60 else 'acknowledged' if index == 60 else 'new', identity))
        result = store.list(group='requests', state='new', limit=1)
        assert len(result['items']) == 1 and result['items'][0]['id'] == ids[61]
        assert result['matched_total'] == 1 and result['has_more'] is False
        assert store.list(group='care', q='63')['items'][0]['case_number'] == 63
        assert store.list(q='1樓1室', state='open')['matched_total'] == 3
        assert store.list(q="%' OR 1=1 --")['matched_total'] == 0
        assert store.list(q='%')['matched_total'] == 0
        assert store.list(sort='created_desc')['items'][0]['id'] == ids[62]
        assert store.list(sort='updated_desc')['items'][0]['id'] == ids[0]
        assert store.list(sort='created_asc', limit=1, offset=1)['items'][0]['id'] == ids[1]
    finally:
        store.db.close()


def test_case_dates_use_selected_field_and_hong_kong_inclusive_end_day(tmp_path):
    store = ServiceDeskStore(tmp_path / 'cases.sqlite3')
    try:
        item = store.create(ResidentCase(submission_id='a' * 32, kind='water', message='公開測試漏水', confirmed=True))
        start = int(datetime(2026, 11, 2, 16, tzinfo=UTC).timestamp() * 1000)
        with store.db:
            store.db.execute('UPDATE service_cases SET created_at_ms=?,updated_at_ms=?,due_at_ms=? WHERE id=?',
                             (start - 1, start + 86399999, 0, item['id']))
        assert store.list(date_field='created', date_from='2026-11-03', date_to='2026-11-03')['matched_total'] == 0
        assert store.list(date_field='updated', date_from='2026-11-03', date_to='2026-11-03')['matched_total'] == 1
        assert store.list(date_field='updated', date_from='2026-11-04')['matched_total'] == 0
        assert store.list(date_field='due', date_from='2026-11-03')['matched_total'] == 0
    finally:
        store.db.close()


def test_event_filters_hide_drills_before_pagination_and_keep_stable_ties():
    store = EventStore()
    try:
        for index in range(105):
            store.add(Event(id=f'evt-{index:03}', type='litter_detected', zone='公開測試大堂', at_ms=1000,
                            severity='notice', details={'is_test': index < 103}))
        page = store.browse(live_only=True, limit=1)
        assert page['matched_total'] == 2 and page['has_more'] is True
        assert page['events'][0].id == 'evt-104'
        other = store.browse(live_only=True, limit=1, offset=1)
        assert other['events'][0].id == 'evt-103' and not other['has_more']
        store.update_status('evt-103', 'confirmed')
        assert store.browse(live_only=True, state='confirmed')['matched_total'] == 1
        assert store.browse(live_only=True, q='垃圾')['matched_total'] == 2
        assert store.browse(live_only=True, q='%')['matched_total'] == 0
        store.update_status('evt-104', 'resolved')
        assert store.browse(live_only=True, sort='completed_desc')['events'][0].id == 'evt-104'
        assert store.browse(live_only=True, state='open')['matched_total'] == 1
    finally:
        store.close()


@pytest.mark.parametrize('kwargs', [{'sort': 'created_at_ms; DROP TABLE events'}, {'state': 'unknown'},
    {'date_from': '2026-02-30'}, {'date_from': '2026-11-04', 'date_to': '2026-11-03'}, {'q': 'x' * 121}])
def test_invalid_filters_are_rejected(kwargs):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        validate('cases', **kwargs)
