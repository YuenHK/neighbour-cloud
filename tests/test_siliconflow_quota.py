import asyncio

import httpx
import pytest

from edge_hub.siliconflow_quota import BalanceReader


def test_only_official_balance_fields_are_exposed():
    result = BalanceReader.normalize({'status': True, 'data': {'balance': '9.25', 'chargeBalance': '0.00', 'totalBalance': '9.25', 'email': 'never-forward@example.test', 'id': 'private-account'}})
    assert result == {'balance': '9.25', 'charge_balance': '0.00', 'total_balance': '9.25'}
    assert 'private' not in str(result) and 'email' not in str(result)


@pytest.mark.parametrize('value', [None, True, 'NaN', 'Infinity', '-1', 'invalid'])
def test_invalid_amounts_stay_unknown(value):
    with pytest.raises(ValueError):
        BalanceReader.normalize({'status': True, 'data': {'balance': value, 'chargeBalance': '0', 'totalBalance': '0'}})


def test_balance_cache_is_honest_after_failure():
    async def scenario():
        now, calls = [0], []
        async def fetch(key):
            calls.append(key)
            if len(calls) > 1:
                raise httpx.ConnectError('private diagnostic is not exposed')
            return {'status': True, 'data': {'balance':'9.25','chargeBalance':'0','totalBalance':'9.25'}}
        reader = BalanceReader(key_provider=lambda:'synthetic-key', fetcher=fetch, clock=lambda:now[0])
        first=await reader.snapshot()
        assert first['status']=='ok' and first['data']['total_balance']=='9.25'
        assert (await reader.snapshot())==first and len(calls)==1
        now[0]=61
        stale=await reader.snapshot()
        assert stale['status']=='stale' and stale['updated_at_ms']==first['updated_at_ms']
        assert 'synthetic' not in str(stale) and 'private' not in str(stale)
    asyncio.run(scenario())
