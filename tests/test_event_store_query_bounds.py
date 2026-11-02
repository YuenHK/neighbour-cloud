import pytest

from edge_hub.events import Event, EventStore


@pytest.mark.parametrize('method,arguments', [
    ('query', {'limit': True}), ('query', {'offset': 1.5}),
    ('query', {'offset': 2**63}), ('query', {'since_ms': 2**63}),
    ('query', {'since_ms': True}),
    ('page', {'after': True}), ('page', {'after': 1.5}), ('page', {'after': 2**63}),
    ('page', {'through': 2**63}), ('page', {'through': -1}),
    ('page', {'limit': True}), ('page', {'limit': 1.5}),
])
def test_internal_query_bounds_reject_before_sql(method, arguments):
    store = EventStore()
    statements = []
    store._connection.set_trace_callback(statements.append)
    try:
        with pytest.raises(ValueError, match='invalid'):
            getattr(store, method)(**arguments)
        assert statements == []
        assert store.latest_cursor() == 0
    finally:
        store.close()


def test_sqlite_integer_boundaries_remain_usable():
    store = EventStore()
    try:
        assert store.query(since_ms=-(2**63), offset=2**63 - 1) == []
        assert store.query(since_ms=2**63 - 1) == []
        page = store.page(after=2**63 - 1, through=2**63 - 1)
        assert page == {'items': [], 'next_cursor': 2**63 - 1, 'has_more': False}
        assert store.page(after=1, through=0)['items'] == []  # Empty interval is still valid.
    finally:
        store.close()


def test_historical_negative_timestamp_is_not_rewritten_or_excluded():
    store = EventStore()
    try:
        store.add(Event(id='legacy', type='robot_fault', zone='test', at_ms=-1, severity='notice'))
        assert store.query(since_ms=-1)[0].at_ms == -1
        assert store.page()['items'][0].at_ms == -1
        assert store.query(since_ms=0) == []
    finally:
        store.close()
