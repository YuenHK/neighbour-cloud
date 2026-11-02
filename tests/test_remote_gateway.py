import asyncio
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from edge_hub.remote_access_runner import traffic_policy
from edge_hub.remote_access_setup import create_setup
from edge_hub.remote_gateway import HOP_HEADER, create_gateway, upstream

DOMAIN = 'synthetic.ngrok-free.dev'
SECRET = 'isolated-hop-proof-'+'a'*40
AUTH = {HOP_HEADER: SECRET, 'Origin': 'https://'+DOMAIN}


class Bytes(httpx.AsyncByteStream):
    def __init__(self, data=b''):
        self.data = data
    async def __aiter__(self):
        if self.data:
            yield self.data


def test_unknown_host_missing_auth_and_cross_origin_write_never_reach_backend():
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, text='private'))
    app = create_gateway(SECRET, [DOMAIN], transport=transport)
    with TestClient(app, base_url='https://'+DOMAIN) as client:
        assert client.get('/admin').status_code == 403
        assert client.get('/__remote/runtime.js').status_code == 403
        assert client.get('/admin', headers={**AUTH, 'Host': 'wrong.invalid'}).status_code == 403
        assert client.post('/api/v1/resident/chat', json={}, headers={**AUTH, 'Origin': 'https://evil.invalid'}).status_code == 403
        assert client.post('/api/v1/resident/chat', json={}, headers={HOP_HEADER: SECRET}).status_code == 403
        assert calls == []


def test_fixed_proxy_routes_html_and_json_keep_private_headers_out_of_backend():
    calls = []
    def respond(request):
        calls.append(request)
        assert HOP_HEADER not in request.headers and 'cookie' not in request.headers
        assert request.url.host == '127.0.0.1'
        if request.url.path == '/admin':
            return httpx.Response(200, headers={'Content-Type': 'text/html'},
                                  text='<html><head></head><iframe src="http://127.0.0.1:4173/ui/estate-settings-entry.html"></iframe></html>')
        return httpx.Response(200, headers={'Content-Type':'application/json'},
                              stream=Bytes(json.dumps({'kept':request.content.decode()}).encode()))
    app = create_gateway(SECRET, [DOMAIN], transport=httpx.MockTransport(respond))
    with TestClient(app, base_url='https://'+DOMAIN) as client:
        response = client.get('/admin', headers={**AUTH, 'Cookie': 'not-for-local-backend', 'X-Forwarded-For': 'private'})
        assert response.status_code == 200
        assert '/__remote/runtime.js' in response.text and 'http://127.0.0.1' not in response.text
        assert 'src="/ui/estate-settings-entry.html"' in response.text
        assert response.headers['cache-control'] == 'no-store'
        result = client.post('/api/v1/resident/chat', json={'messages': [{'role':'user','content':'公開虛構文字'}]}, headers=AUTH)
        assert result.status_code == 200 and '公開虛構文字' in result.json()['kept']
        assert calls[-1].headers['origin'] == 'http://127.0.0.1:8000'
        client.get('/_audio/health', headers=AUTH)
        assert calls[-1].url.port == 8765 and calls[-1].url.path == '/health'
        client.get('/assets/pages-hash.js', headers=AUTH)
        assert calls[-1].url.port == 4173
        client.get('/assets/service/service-shell.js', headers=AUTH)
        assert calls[-1].url.port == 8000
    for path in ('//evil.invalid', '/http://evil.invalid', '/_audioevil/health', '/%2f%2fevil.invalid'):
        assert upstream(path)[0] in ('http://127.0.0.1:8000','http://127.0.0.1:4173')


def test_sse_bytes_and_local_redirect_are_preserved_without_extra_request():
    class Events(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"first":true}\n\n'
            yield b'data: [DONE]\n\n'
    calls = []
    def respond(request):
        calls.append(str(request.url))
        if request.url.path == '/go':
            return httpx.Response(307, headers={'Location':'http://127.0.0.1:4173/settings'}, stream=Bytes())
        return httpx.Response(200, headers={'Content-Type':'text/event-stream'}, stream=Events())
    app = create_gateway(SECRET, [DOMAIN], transport=httpx.MockTransport(respond))
    with TestClient(app, base_url='https://'+DOMAIN) as client:
        response = client.get('/api/v1/public-fixture-stream', headers=AUTH)
        assert response.content == b'data: {"first":true}\n\ndata: [DONE]\n\n'
        response = client.get('/go', headers=AUTH, follow_redirects=False)
        assert response.status_code == 307 and response.headers['location'] == '/settings'
        assert len(calls) == 2


def test_websocket_both_directions_and_binary_frames_are_relayed_without_real_socket(monkeypatch):
    connections = []
    class Socket:
        subprotocol = None
        def __init__(self):
            self.queue = asyncio.Queue()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def send(self, item):
            await self.queue.put(item)
        async def __aiter__(self):
            while True:
                yield await self.queue.get()
    def connect(url, **kwargs):
        connections.append((url, kwargs))
        return Socket()
    monkeypatch.setattr('edge_hub.remote_gateway.websockets.connect', connect)
    with (TestClient(create_gateway(SECRET, [DOMAIN]), base_url='https://'+DOMAIN) as client,
          client.websocket_connect('/_airi/ws', headers={**AUTH,'Host':DOMAIN}) as socket):
        socket.send_text('public-event')
        assert socket.receive_text() == 'public-event'
        socket.send_bytes(b'public')
        assert socket.receive_bytes() == b'public'
    assert connections[0][0] == 'ws://127.0.0.1:6121/ws'
    assert connections[0][1]['origin'] == 'http://127.0.0.1:4173'


def test_local_setup_encrypts_once_refuses_overwrite_and_never_echoes_validation_input(tmp_path):
    root = tmp_path/'private'
    app = create_setup(root, domain=DOMAIN, protect=lambda value, **kwargs: b'encrypted-not-token')
    with TestClient(app, base_url='http://127.0.0.1:8002', client=('127.0.0.1',1234)) as client:
        page = client.get('/')
        nonce = re.search(r'nonce:("[A-Za-z0-9_-]+")', page.text)[1].strip('"')
        body = {'token':'synthetic-token-not-real', 'email':'owner@example.org', 'nonce':nonce}
        bad = client.post('/save', json={**body,'token':'sensitive invalid value'}, headers={'Origin':'http://127.0.0.1:8002'})
        assert bad.status_code == 422 and 'sensitive' not in bad.text
        assert client.post('/save', json=body, headers={'Origin':'https://evil.invalid'}).status_code == 403
        response = client.post('/save', json=body, headers={'Origin':'http://127.0.0.1:8002'})
        assert response.status_code == 200 and response.json() == {'saved':True,'published':False}
        assert (root/'ngrok-token.dpapi').read_bytes() == b'encrypted-not-token'
        assert 'synthetic-token' not in (root/'settings.json').read_text()
        assert client.post('/save', json=body, headers={'Origin':'http://127.0.0.1:8002'}).status_code == 409
        assert client.get('/', headers={'X-Forwarded-Host':DOMAIN}).status_code == 403


def test_missing_secret_never_starts_gateway():
    with pytest.raises(ValueError):
        create_gateway('', [DOMAIN])


def test_edge_policy_requires_google_and_exact_account_before_hop_header():
    rules = traffic_policy('owner@example.org', 'a'*40)['on_http_request']
    assert rules[0]['actions'][0]['type'] == 'oauth'
    assert rules[0]['actions'][0]['config']['provider'] == 'google'
    assert rules[1]['expressions'] == ['actions.ngrok.oauth.identity.email != "owner@example.org"']
    assert rules[1]['actions'] == [{'type': 'deny'}]
    assert [action['type'] for action in rules[2]['actions']] == ['remove-headers', 'add-headers']
    assert rules[2]['actions'][1]['config']['headers'][HOP_HEADER] == 'a'*40
    with pytest.raises(ValueError):
        traffic_policy("invalid' || true", 'a'*40)
