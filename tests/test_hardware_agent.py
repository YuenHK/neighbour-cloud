import json

import httpx
import pytest
from fastapi.testclient import TestClient

from edge_hub.ep_console import EpBroker
from edge_hub.hardware_agent import create_agent
from edge_hub.local_operator import LOCAL_OPERATOR_TOKEN
from edge_hub.remote_gateway import HOP_HEADER, create_gateway


def test_start_and_read_fleet_never_create_sdk_or_resident_store(tmp_path, monkeypatch):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    marker = runtime / 'cloud-primary.json'
    marker.write_text(json.dumps({'format': 'neighbour-cloud-primary-v1', 'phase': 'cloud',
        'origin': 'https://neighbour-yuenhk-live.onrender.com', 'release_id': 'a' * 32}))
    original = marker.read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail('SDK must not start for idle agent/read-only UI')
    monkeypatch.setattr(EpBroker, '_start', forbidden)
    app = create_agent(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 50000)) as client:
        assert client.get('/health').json()['resident_writer'] is False
        page = client.get('/robots')
        assert page.status_code == 200 and LOCAL_OPERATOR_TOKEN in page.text
        assert 'ep-background.js' not in page.text
        assert client.get('/api/v1/robot/ep/fleet').status_code == 403
        reply = client.get('/api/v1/robot/ep/fleet', headers={'X-Operator-Key': LOCAL_OPERATOR_TOKEN})
        assert reply.status_code == 200 and reply.json()['devices'] == []
        assert client.get('/robots', headers={'Host': 'evil.invalid'}).status_code == 403
        assert client.get('/api/v1/service-desk/requests').status_code == 404
        assert app.state.broker.monitor_thread is None
    assert marker.read_bytes() == original
    assert list(runtime.iterdir()) == [marker]


def test_remote_hardware_mode_is_authenticated_and_cannot_reach_old_data_services():
    calls = []
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"synthetic":true}'
    def respond(request):
        calls.append(request)
        assert request.url.port == 8000
        assert request.headers['origin'] == 'http://127.0.0.1:8000'
        assert request.headers['sec-fetch-site'] == 'same-origin'
        assert HOP_HEADER not in request.headers
        return httpx.Response(200, headers={'Content-Type': 'application/json'}, stream=Bytes())
    proof = 's' * 40
    domain = 'synthetic.ngrok-free.app'
    app = create_gateway(proof, [domain], transport=httpx.MockTransport(respond), hardware_only=True)
    headers = {HOP_HEADER: proof, 'Origin': 'https://' + domain, 'Sec-Fetch-Site': 'cross-site'}
    with TestClient(app, base_url='https://' + domain) as client:
        assert client.get('/robots').status_code == 403
        assert client.post('/api/v1/robot/ep/fake/stop', headers=headers, json={}).status_code == 200
        assert client.get('/assets/ep-fleet.js', headers=headers).status_code == 200
        for path in ('/admin', '/api/v1/service-desk/requests', '/_audio/health', '/assets/private.js'):
            assert client.get(path, headers=headers).status_code == 404
    assert len(calls) == 2
