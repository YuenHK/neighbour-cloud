import sys

import pytest
from fastapi.testclient import TestClient

from edge_hub.app import app, ep_broker
from edge_hub.local_operator import LOCAL_OPERATOR_TOKEN
from edge_hub.wifi_profile import WifiError, profile_values


@pytest.fixture
def console(monkeypatch, tmp_path):
    # Never depend on the deployed machine's persistent incident hold.
    monkeypatch.setattr(ep_broker, 'root', tmp_path)
    return TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))


AUTH = {'X-Operator-Key': LOCAL_OPERATOR_TOKEN}


def test_page_and_passive_status_do_not_read_wifi_start_worker_or_import_sdk(console, monkeypatch):
    monkeypatch.setattr(ep_broker, '_start', lambda: pytest.fail('must not launch SDK worker'))
    monkeypatch.setattr('edge_hub.ep_console.current_wifi', lambda **_: pytest.fail('must not read Wi-Fi'))
    assert console.get('/ep-preparation').status_code == 200
    response = console.get('/api/v1/robot/ep/connection', headers=AUTH)
    assert response.status_code == 200
    assert response.json()['connection'] == 'not_connected'
    assert 'robomaster' not in sys.modules


def test_current_wifi_qr_keeps_password_inside_broker_and_never_in_response(console, monkeypatch):
    calls = []
    monkeypatch.setattr('edge_hub.ep_console.current_wifi', lambda **_: {
        'ssid': 'Synthetic-EP', 'password': 'synthetic-wifi-only'})
    def request(operation, body):
        calls.append((operation, body))
        return {'ssid': body['ssid'], 'svg_base64': 'PHN2Zy8+', 'expires_in_seconds': 120}
    monkeypatch.setattr(ep_broker, 'request', request)
    response = console.post('/api/v1/robot/ep/qr', headers=AUTH, json={'use_current_wifi': True})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert 'synthetic-wifi-only' not in response.text
    assert calls == [('qr', {'ssid': 'Synthetic-EP', 'password': 'synthetic-wifi-only'})]


def test_denied_windows_key_returns_manual_fallback_without_retry(console, monkeypatch):
    def deny(**kwargs):
        raise WifiError('請在本頁隱藏欄位輸入')
    monkeypatch.setattr('edge_hub.ep_console.current_wifi', deny)
    response = console.post('/api/v1/robot/ep/qr', headers=AUTH, json={'use_current_wifi': True})
    assert response.status_code == 409
    assert '隱藏欄位' in response.json()['detail']


def test_each_qr_request_reads_the_current_network_instead_of_caching_home_wifi(console, monkeypatch):
    networks = iter([
        {'ssid': 'Synthetic-Home', 'password': 'synthetic-home-only'},
        {'ssid': 'Synthetic-Exhibition', 'password': 'synthetic-exhibition-only'},
    ])
    received = []
    monkeypatch.setattr('edge_hub.ep_console.current_wifi', lambda **_: next(networks))
    def request(operation, body):
        received.append(dict(body))
        return {'ssid': body['ssid'], 'svg_base64': 'PHN2Zy8+', 'expires_in_seconds': 120}
    monkeypatch.setattr(ep_broker, 'request', request)
    for _ in range(2):
        result = console.post('/api/v1/robot/ep/qr', headers=AUTH, json={'use_current_wifi': True})
        assert result.status_code == 200
        assert 'password' not in result.json()
    assert received == [
        {'ssid': 'Synthetic-Home', 'password': 'synthetic-home-only'},
        {'ssid': 'Synthetic-Exhibition', 'password': 'synthetic-exhibition-only'},
    ]


def test_connect_requires_explicit_on_site_confirmation_and_key(console, monkeypatch):
    monkeypatch.setattr(ep_broker, 'request', lambda *_: pytest.fail('must not initialize EP'))
    assert console.post('/api/v1/robot/ep/connect', headers=AUTH,
                        json={'ip': '192.168.1.2'}).status_code == 422
    assert console.post('/api/v1/robot/ep/connect', headers=AUTH,
                        json={'ip': '192.168.1.2', 'confirmed': False}).status_code == 422
    assert console.post('/api/v1/robot/ep/connect',
                        json={'ip': '192.168.1.2', 'confirmed': True}).status_code == 403


def test_external_origin_and_rebound_host_cannot_read_current_wifi(console, monkeypatch):
    monkeypatch.setattr('edge_hub.ep_console.current_wifi', lambda **_: pytest.fail('must not read password'))
    for headers in ({**AUTH, 'Origin': 'https://example.com'}, {**AUTH, 'Host': 'evil.example:8000'}):
        assert console.post('/api/v1/robot/ep/qr', headers=headers,
                            json={'use_current_wifi': True}).status_code == 403


def test_validation_never_echoes_manual_wifi_password(console):
    response = console.post('/api/v1/robot/ep/qr', headers=AUTH,
                            json={'password': 'synthetic-secret', 'unexpected': True})
    assert response.status_code == 422
    assert 'synthetic-secret' not in response.text


def test_encrypted_windows_profile_is_not_mistaken_for_plaintext_password():
    xml = ('<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
           '<MSM><security><authEncryption><authentication>WPA2PSK</authentication></authEncryption>'
           '<sharedKey><protected>true</protected><keyMaterial>encrypted-only</keyMaterial>'
           '</sharedKey></security></MSM></WLANProfile>')
    with pytest.raises(WifiError):
        profile_values(xml)
    assert profile_values(xml.replace('<protected>true', '<protected>false')) == 'encrypted-only'
