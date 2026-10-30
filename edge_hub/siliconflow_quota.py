"""Read-only official account balance; no billing, generation or personal fields."""
from decimal import Decimal, InvalidOperation

import httpx

from edge_hub.api_quota import QuotaReader
from edge_hub.cloud_credentials import credential_path, siliconflow_key


def key():
    return siliconflow_key() if credential_path().is_file() else ''


class BalanceReader(QuotaReader):
    def __init__(self, **kwargs):
        super().__init__(key_provider=kwargs.pop('key_provider', key), **kwargs)

    @staticmethod
    def normalize(payload):
        if payload.get('status') is not True:
            raise ValueError('account balance not confirmed')
        data = payload.get('data') or {}
        result = {}
        for source, target in (('balance', 'balance'), ('chargeBalance', 'charge_balance'), ('totalBalance', 'total_balance')):
            raw = data.get(source)
            if not isinstance(raw, (str, int)) or isinstance(raw, bool) or len(str(raw)) > 64:
                raise ValueError('invalid balance')
            try:
                value = Decimal(str(raw))
            except InvalidOperation:
                raise ValueError('invalid balance') from None
            if not value.is_finite() or value < 0:
                raise ValueError('invalid balance')
            result[target] = str(value)
        return result

    @staticmethod
    async def fetch(credential):
        async with httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False) as client:
            response = await client.get('https://api.siliconflow.cn/v1/user/info', headers={'Authorization': 'Bearer '+credential})
            response.raise_for_status()
            return response.json()
