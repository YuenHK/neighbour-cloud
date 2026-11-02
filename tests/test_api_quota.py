import asyncio

import httpx

from edge_hub.api_quota import QuotaReader, normalize_usage


def usage(used=20, limit=1000, key_used=10, key_limit=None):
    return {'account': {'current_plan': 'Researcher', 'plan_usage': used, 'plan_limit': limit},
            'key': {'usage': key_used, 'limit': key_limit}}


def test_account_and_key_limits_are_not_added_or_treated_as_unlimited():
    result = normalize_usage(usage(key_limit=100))
    assert result['remaining'] == 980 and result['key_remaining'] == 90
    assert result['effective_remaining'] == 90
    assert normalize_usage(usage())['key_remaining'] is None
    assert normalize_usage(usage(used=1002))['remaining'] == 0


def test_absent_and_invalid_counters_stay_unknown_instead_of_zero():
    assert normalize_usage({'account': {}, 'key': {}})['remaining'] is None
    assert normalize_usage(usage(used=True))['remaining'] is None
    assert normalize_usage(usage(limit=-1))['remaining'] is None


def test_quota_cache_stale_state_and_rotation_are_account_aware():
    async def scenario():
        clock = [0]
        key = ['synthetic-old-key']
        calls = []
        async def fetch(value):
            calls.append(value)
            if len(calls) > 1:
                raise httpx.ConnectError('not forwarded')
            return usage()
        reader = QuotaReader(key_provider=lambda: key[0], fetcher=fetch, clock=lambda: clock[0])
        first = await reader.snapshot()
        assert first['status'] == 'ok' and first['data']['remaining'] == 980
        assert await reader.snapshot() == first and len(calls) == 1
        clock[0] = 61
        stale = await reader.snapshot()
        assert stale['status'] == 'stale' and stale['updated_at_ms'] == first['updated_at_ms']
        key[0] = 'synthetic-different-account'
        changed = await reader.snapshot()
        assert changed['status'] == 'unavailable' and changed['data'] is None
        assert 'synthetic' not in str(changed)
    asyncio.run(scenario())


def test_missing_key_does_not_call_provider():
    async def scenario():
        async def fetch(key):
            raise AssertionError('no key must not call provider')
        reader = QuotaReader(key_provider=lambda: '', fetcher=fetch)
        assert (await reader.snapshot())['status'] == 'not_configured'
    asyncio.run(scenario())
