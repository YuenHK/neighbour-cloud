import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import test_cloud_http_app

prepared = test_cloud_http_app.prepared
seeded = test_cloud_http_app.seeded
keys = test_cloud_http_app.keys
api = test_cloud_http_app.api
URL = '/api/v1/service-desk/quota'


@pytest.fixture
def quota(api, monkeypatch):
    from deploy.cloud import quota_api

    root = api.services.storage.settings_root
    (root / 'azure-speech-f0.json').write_text(json.dumps({'sku': 'F0', 'region': 'eastasia'}))
    (root / 'azure-speech-f0-key.dpapi').write_bytes(b'SYNTHETIC-REFERENCE')
    (root / 'cloudflare-gemma-free.json').write_text(json.dumps({
        'enabled': True, 'plan': 'Free', 'ui_verified': True, 'account_id': 'a' * 32}))
    (root / 'cloudflare-gemma-key.dpapi').write_bytes(b'SYNTHETIC-REFERENCE')
    secret, clock, answer, calls = ['SYNTHETIC-SEARCH-SECRET'], [0], [200], []
    monkeypatch.setattr(quota_api, 'search_key', lambda: secret[0])

    async def respond(request):
        calls.append(request)
        assert request.method == 'GET' and str(request.url) == 'https://api.tavily.com/usage'
        assert request.headers['Authorization'] == 'Bearer ' + secret[0]
        assert api.staff['Authorization'] not in str(request.headers)
        if answer[0] == 'large':
            return httpx.Response(200, content=b'x' * 65537)
        if answer[0] == 'redirect':
            return httpx.Response(307, headers={'Location': 'https://other.example/PRIVATE'})
        if answer[0] == 'malformed':
            return httpx.Response(200, json={'account': {'plan_usage': True, 'plan_limit': -1}})
        if answer[0] != 200:
            return httpx.Response(answer[0], text='PRIVATE-ERROR-DETAIL')
        return httpx.Response(200, json={'account': {'plan_usage': 42, 'plan_limit': 1000,
            'current_plan': 'PRIVATE-ACCOUNT', 'paygo_usage': 7}, 'key': {'usage': 2, 'limit': 100},
            'private_field': 'MUST-NOT-BE-RETURNED'})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    api.app.app.state.quota_client = client
    api.app.app.state.quotas.reader.clock = lambda: clock[0]
    try:
        yield api, calls, secret, clock, answer
    finally:
        asyncio.run(client.aclose())


def rows(response):
    assert response.status_code == 200
    return {row['id']: row for row in response.json()['overview']['active_rows']}


def test_only_active_services_show_real_persistent_guards_and_reported_official_quota(quota):
    api, calls, _, _, _ = quota
    response = api.client.get(URL, headers=api.staff)
    result = rows(response)
    assert set(result) == {'cloudflare-gemma', 'azure-voice', 'tavily', 'tavily-key'}
    assert result['cloudflare-gemma']['guard']['counters'][0]['used'] == 456
    assert result['azure-voice']['guard']['counters'][0]['used'] == 123
    assert result['cloudflare-gemma']['provider']['percent'] is None
    assert result['azure-voice']['provider']['remaining'] is None
    assert result['tavily']['provider']['remaining'] == 958
    assert result['tavily']['provider']['percent'] == 95.8
    assert result['tavily-key']['provider']['remaining'] == 98
    assert result['tavily']['provider']['source'] == 'tavily_usage_api'
    assert result['tavily']['provider']['reset_at'] is None
    assert result['azure-voice']['provider']['reset_at'] is None
    assert result['azure-voice']['operation']['state'] == 'paused'
    assert result['cloudflare-gemma']['operation']['blocked'] is False
    assert response.json()['overview']['other_rows'] == []
    assert '本機 SenseVoice' not in response.text
    assert all(marker not in response.text for marker in ('SYNTHETIC', 'PRIVATE', 'MUST-NOT', 'siliconflow', 'HKSoft'))
    assert response.headers['cache-control'] == 'no-store'
    assert len(calls) == 1 and api.calls == [] and api.search.await_count == 0
    assert not (api.services.storage.settings_root / 'cloud-usage.sqlite3').exists()
    assert api.services.journal.recent()[0]['route'] == URL


def test_auth_and_query_cannot_force_an_unlimited_official_refresh(quota):
    api, calls, _, _, _ = quota
    assert api.client.get(URL).status_code == 401
    assert api.client.get(URL, headers=api.resident).status_code == 403
    assert api.client.get(URL, headers={**api.staff, 'Origin': 'https://other.example'}).status_code == 403
    assert calls == []
    for _ in range(3):
        assert api.client.get(URL, headers=api.staff).status_code == 200
    assert len(calls) == 1
    assert api.client.get(URL + '?refresh=true', headers=api.staff).status_code == 400
    assert api.client.put(URL, headers=api.staff, json={'paid': True}).status_code == 405
    assert len(calls) == 1


def test_official_failure_is_cached_stale_then_key_rotation_clears_old_account_data(quota):
    api, calls, secret, clock, answer = quota
    assert rows(api.client.get(URL, headers=api.staff))['tavily']['provider']['status'] == 'ok'
    clock[0] = 61
    answer[0] = 429
    stale = rows(api.client.get(URL, headers=api.staff))['tavily']['provider']
    assert stale['status'] == 'stale' and stale['remaining'] == 958
    assert api.client.get(URL, headers=api.staff).status_code == 200 and len(calls) == 2
    secret[0] = 'SYNTHETIC-DIFFERENT-ACCOUNT'
    unknown = rows(api.client.get(URL, headers=api.staff))['tavily']['provider']
    assert unknown['status'] == 'unavailable' and unknown['remaining'] is None
    assert len(calls) == 3


def test_missing_usage_or_control_cannot_report_zero_or_available(quota):
    api, _, _, _, _ = quota
    storage = api.services.storage
    db = storage.connect(storage.settings_root / 'cloud-usage.sqlite3')
    try:
        db.execute('DROP TABLE usage')
        db.commit()
    finally:
        db.close()
    storage.controls.db.execute("DELETE FROM cloud_state WHERE name='azure-voice-control.json'")
    storage.controls.db.commit()
    result = rows(api.client.get(URL, headers=api.staff))
    for identity in ('azure-voice', 'cloudflare-gemma'):
        assert result[identity]['guard']['status'] == 'unavailable'
        assert result[identity]['guard']['counters'][0]['used'] is None
        assert result[identity]['operation']['blocked'] is True


def test_utc_guard_period_rollover_and_unknown_official_dates_do_not_reset_data(quota):
    from deploy.cloud.quota_api import local_overview

    api, _, _, _, _ = quota
    stamp = datetime(2026, 10, 31, 23, 59, tzinfo=UTC)
    with api.services.scope():
        result = local_overview(now=stamp)
    result = {row['id']: row for row in result}
    assert result['cloudflare-gemma']['guard']['reset_at'] == '2026-11-01T00:00:00Z'
    assert result['azure-voice']['guard']['reset_at'] == '2026-11-01T00:00:00Z'
    assert result['azure-voice']['provider']['reset_at'] is None
    db = api.services.storage.connect(api.services.storage.settings_root / 'cloud-usage.sqlite3')
    try:
        assert db.execute("SELECT SUM(amount) FROM usage WHERE meter='azure_tts_characters'").fetchone()[0] == 123
    finally:
        db.close()


@pytest.mark.parametrize('failure', ['large', 'redirect', 'malformed'])
def test_invalid_official_reply_is_unknown_bounded_and_not_retried(quota, failure):
    api, calls, _, _, answer = quota
    answer[0] = failure
    for _ in range(2):
        response = api.client.get(URL, headers=api.staff)
        result = rows(response)
        assert result['tavily']['provider']['status'] == 'unavailable'
        assert result['tavily']['provider']['remaining'] is None
        assert result['cloudflare-gemma']['guard']['counters'][0]['used'] == 456
        assert 'PRIVATE' not in response.text
    assert len(calls) == 1


def test_no_search_key_never_issues_a_provider_call(quota):
    api, calls, secret, _, _ = quota
    secret[0] = ''
    result = rows(api.client.get(URL, headers=api.staff))
    assert result['tavily']['provider']['status'] == 'not_configured'
    assert result['tavily']['provider']['remaining'] is None and calls == []


def test_stale_prior_month_cannot_be_presented_as_current_month_remaining():
    from deploy.cloud.quota_api import search_rows

    old = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
    previous = {'status': 'stale', 'data': {'used': 42, 'limit': 1000, 'key_used': 2, 'key_limit': 100},
                'updated_at_ms': int(old.timestamp() * 1000)}
    result = search_rows(previous)
    assert result[0]['provider']['status'] == 'unavailable'
    assert result[0]['provider']['remaining'] is None and len(result) == 1


def test_slow_official_stream_is_closed_at_total_deadline_without_looping(quota, monkeypatch):
    from deploy.cloud import quota_api

    api, _, _, _, _ = quota
    monkeypatch.setattr(quota_api, 'QUOTA_DEADLINE', .02)
    state = []

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            state.append('reading')
            await asyncio.Event().wait()
            yield b'never'

        async def aclose(self):
            state.append('closed')

    async def respond(request):
        state.append('called')
        return httpx.Response(200, stream=Slow())

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    previous = api.app.app.state.quota_client
    api.app.app.state.quota_client = client
    try:
        for _ in range(2):
            result = rows(api.client.get(URL, headers=api.staff))
            assert result['tavily']['provider']['status'] == 'unavailable'
        assert state == ['called', 'reading', 'closed']
    finally:
        api.app.app.state.quota_client = previous
        asyncio.run(client.aclose())
