import re

import pytest
from fastapi.testclient import TestClient

from edge_hub.app import app


def token_from(page):
    match = re.search(r'id="(?:operatorKey|epKey|memoryKey|controlKey)" type="hidden" value="([^"]*)"', page.text)
    assert match is not None
    return match.group(1)


@pytest.mark.parametrize('page', ['/admin', '/ep-preparation', '/assistant-memory', '/simulation-control'])
def test_local_pages_need_no_password_and_do_not_cache_capability(page):
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    response = client.get(page)
    assert response.status_code == 200
    assert not re.search(r'id="(?:operatorKey|epKey|memoryKey|controlKey)" type="password"', response.text)
    assert response.headers['cache-control'] == 'no-store'
    token = token_from(response)
    assert len(token) >= 32
    status = client.get('/api/v1/robot/ep/preparation', headers={'X-Operator-Key': token})
    assert status.status_code == 200
    assert status.json()['connection'] == 'not_connected'
    assert status.json()['motion_enabled'] is False


@pytest.mark.parametrize('base_url,peer,headers', [
    ('http://127.0.0.1:8000', '192.0.2.1', {}),
    ('http://rebound.example:8000', '127.0.0.1', {}),
    ('http://127.0.0.1:8000', '127.0.0.1', {'Origin': 'https://example.com'}),
    ('http://127.0.0.1:8000', '127.0.0.1', {'Sec-Fetch-Site': 'cross-site'}),
])
def test_remote_cross_site_and_rebound_hosts_receive_no_local_authority(base_url, peer, headers):
    local = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    token = token_from(local.get('/ep-preparation'))
    other = TestClient(app, base_url=base_url, client=(peer, 12001))
    page = other.get('/ep-preparation', headers=headers)
    assert token_from(page) == ''
    result = other.get('/api/v1/robot/ep/preparation', headers={**headers, 'X-Operator-Key': token})
    assert result.status_code == 403


def test_api_still_rejects_requests_without_a_local_page_capability():
    local = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    assert local.get('/api/v1/robot/ep/preparation').status_code == 403
    assert local.get('/api/v1/assistant/memories').status_code == 403
