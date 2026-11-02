from fastapi.testclient import TestClient

from edge_hub.app import app, ep_broker


def test_discovery_is_common_to_all_three_pages_and_has_no_get_side_effect(monkeypatch):
    calls = []
    monkeypatch.setattr(ep_broker, 'renew_discovery', lambda: calls.append('renew') or {'enabled': True})
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    for path in ('/', '/admin', '/robots'):
        response = client.get(path)
        assert response.status_code == 200
        assert response.text.count('src="/assets/service/ep-background.js"') == 1
    assert not calls
    assert client.get('/assets/service/ep-background.js').status_code == 200
    assert client.post('/api/v1/robot/ep/discovery').status_code == 200
    assert calls == ['renew']
    assert client.post('/api/v1/robot/ep/discovery', headers={'Origin': 'https://outside.invalid'}).status_code == 403
    remote = TestClient(app, base_url='http://127.0.0.1:8000', client=('192.168.1.20', 12000))
    assert remote.post('/api/v1/robot/ep/discovery').status_code == 403
    assert calls == ['renew']
