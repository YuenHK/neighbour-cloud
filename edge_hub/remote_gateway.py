"""Loopback-only, same-origin gateway behind an authenticated ngrok endpoint.

The edge injects a fresh random hop secret after removing client-supplied copies.
Hardware mode validates the existing cloud staff session on every robot request;
legacy whole-site mode retains Google OAuth and exact email allowlisting.
Neither mode exposes unauthenticated loopback services on its own.
"""
import asyncio
import hmac
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse

from edge_hub.robot_platform_auth import PlatformStaff

HOP_HEADER = 'x-neighbour-proxy'
DROP = {'host', 'connection', 'keep-alive', 'transfer-encoding', 'upgrade', 'proxy-authorization',
        'proxy-authenticate', 'te', 'trailer', HOP_HEADER, 'cookie'}
HTML_LIMIT = 2*1024*1024
BODY_LIMIT = 64*1024*1024


def upstream(path):
    for prefix, origin in (('/_audio', 'http://127.0.0.1:8765'),
                           ('/_airi', 'http://127.0.0.1:6121'),
                           ('/_ollama', 'http://127.0.0.1:11434')):
        if path == prefix or path.startswith(prefix+'/'):
            return origin, path[len(prefix):] or '/'
    if (path.startswith(('/ui/', '/settings', '/estate-'))
            or path.startswith('/assets/') and not path.startswith('/assets/service')
            or path in ('/airi-local-profile.json', '/manifest.webmanifest', '/favicon.ico')):
        return 'http://127.0.0.1:4173', path
    return 'http://127.0.0.1:8000', path


def remote_html(data):
    text = data.decode('utf-8')
    for origin, replacement in (('http://127.0.0.1:4173', ''), ('http://127.0.0.1:8000', ''),
                                ('http://127.0.0.1:8765', '/_audio')):
        text = text.replace(origin, replacement)
    injection = '<script src="/__remote/runtime.js"></script>'
    return text.replace('<head>', '<head>'+injection, 1) if '<head>' in text else injection+text


def headers_for_backend(headers, origin):
    result = {key: value for key, value in headers.items() if key.lower() not in DROP
              and not key.lower().startswith(('x-forwarded-', 'ngrok-'))}
    # Backend loopback checks stay intact. The independent edge authentication,
    # hop proof, host and browser-origin checks must have succeeded before this.
    if 'origin' in result:
        result['origin'] = 'http://127.0.0.1:4173' if origin.endswith(':4173') else 'http://127.0.0.1:8000'
    return result


def hardware_path(path):
    return (path in ('/', '/robots', '/health', '/assets/ep-fleet.js', '/assets/ep-fleet.css',
                     '/assets/ep-console.js', '/assets/ep-console.css', '/assets/service-shell.css',
                     '/assets/service/service-mark.svg', '/__remote/runtime.js')
            or path.startswith('/api/v1/robot/ep/'))


def create_gateway(secret, hosts, *, transport=None, hardware_only=False, cloud_origin=None, cloud_authorization=False):
    if not isinstance(secret, str) or len(secret) < 32 or not secret.isascii():
        raise ValueError('A fresh edge hop secret is required')
    hosts = frozenset(hosts)
    if not hosts or any(not isinstance(host, str) or '/' in host or ':' in host for host in hosts):
        raise ValueError('Exact remote hosts are required')
    if cloud_authorization and (not hardware_only or not isinstance(cloud_origin, str)
            or not re.fullmatch(r'https://[a-z0-9-]+\.onrender\.com', cloud_origin)):
        raise ValueError('Exact owned cloud origin is required')
    staff = PlatformStaff(cloud_origin) if cloud_authorization else None
    local_token = None

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                    timeout=httpx.Timeout(120, connect=3, pool=3),
                                    limits=httpx.Limits(max_connections=32, max_keepalive_connections=16)) as client:
            app.state.proxy = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def trusted(headers, *, mutation=False):
        host = headers.get('host', '')
        try:
            authorized = hmac.compare_digest(headers.get(HOP_HEADER, ''), secret)
        except TypeError:
            return False
        allowed_origin = cloud_origin if cloud_authorization else 'https://' + host
        return (authorized and host in hosts and (not mutation or headers.get('origin') == allowed_origin))

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    async def proxy(request: Request, path: str):
        nonlocal local_token
        if not trusted(request.headers, mutation=request.method not in ('GET', 'HEAD', 'OPTIONS')):
            return JSONResponse({'detail': '請透過已登入的鄰伴遠端入口使用。'}, status_code=403,
                                headers={'Cache-Control': 'no-store'})
        if staff is not None and path == '__remote/health':
            return JSONResponse({'ready': True, 'authentication': 'platform_staff'}, headers={'Cache-Control': 'no-store'})
        if staff is not None and not await staff.accepts(request.headers.get('authorization'), app.state.proxy):
            return JSONResponse({'detail': '請先登入鄰伴管理工作台。'}, status_code=401,
                                headers={'Cache-Control': 'no-store'})
        path = '/'+path
        if staff is not None and not path.startswith('/api/v1/robot/ep/'):
            raise HTTPException(404, '請在鄰伴管理工作台內操作機械人。')
        if hardware_only and not hardware_path(path):
            raise HTTPException(404)
        if path == '/__remote/runtime.js':
            return Response((Path(__file__).parent/'static/remote-runtime.js').read_bytes(), media_type='text/javascript',
                            headers={'Cache-Control': 'no-store'})
        if path.startswith('/__remote/'):
            raise HTTPException(404)
        if request.headers.get('content-length', '').isdecimal() and int(request.headers['content-length']) > BODY_LIMIT:
            raise HTTPException(413)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > BODY_LIMIT:
                raise HTTPException(413)
        origin, target = upstream(path)
        if hardware_only:
            origin = 'http://127.0.0.1:8000'
        url = origin+target+('?' + request.url.query if request.url.query else '')
        forwarded = headers_for_backend(request.headers, origin)
        if hardware_only:
            # The authenticated platform/legacy edge is the remote caller. Preserve
            # native loopback policy; client-supplied fetch metadata is not proof.
            forwarded['sec-fetch-site'] = 'same-origin'
        if staff is not None:
            forwarded.pop('authorization', None)
            if path.startswith('/api/v1/robot/ep/'):
                if local_token is None:
                    # Fetch the process-scoped capability from our own loopback
                    # console. Never expose it or the staff token to the client.
                    try:
                        page = await app.state.proxy.get('http://127.0.0.1:8000/robots', timeout=3)
                        match = re.search(r'id="epKey"[^>]*value="([A-Za-z0-9_-]{32,100})"', page.text)
                        if page.status_code != 200 or match is None:
                            raise ValueError('local_operator_unavailable')
                        local_token = match[1]
                    except (httpx.HTTPError, ValueError):
                        return JSONResponse({'detail': '現場控制台尚未啟動。'}, status_code=503)
                forwarded['x-operator-key'] = local_token
        try:
            outgoing = app.state.proxy.build_request(request.method, url, headers=forwarded, content=bytes(body))
            response = await app.state.proxy.send(outgoing, stream=True)
            if staff is not None and response.status_code == 403:
                local_token = None  # No automatic replay of a robot command.
        except httpx.HTTPError:
            return JSONResponse({'detail': '現場服務暫時未能連接，請稍後再試。'}, status_code=502)
        headers = {key: value for key, value in response.headers.items()
                   if key.lower() not in DROP and not key.lower().startswith('access-control-')
                   and key.lower() != 'set-cookie'}
        headers.update({'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'SAMEORIGIN',
                        'Referrer-Policy': 'no-referrer', 'Service-Worker-Allowed': '/__remote/disabled/'})
        if 'location' in headers:
            value = headers['location']
            for local, prefix in (('http://127.0.0.1:8000', ''), ('http://127.0.0.1:4173', ''),
                                  ('http://127.0.0.1:8765', '/_audio')):
                if value.startswith(local+'/'):
                    headers['location'] = prefix+value[len(local):]
        if 'text/html' in response.headers.get('content-type', '') and request.method != 'HEAD':
            try:
                data = await response.aread()
                if len(data) > HTML_LIMIT:
                    raise ValueError('oversized local page')
                data = remote_html(data)
            except (ValueError, UnicodeError):
                raise HTTPException(502, '現場頁面暫時未能載入。') from None
            finally:
                await response.aclose()
            for key in ('content-length', 'content-encoding', 'etag'):
                headers.pop(key, None)
            headers['cache-control'] = 'no-store'
            return Response(data, status_code=response.status_code, headers=headers)

        async def chunks():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()
        return StreamingResponse(chunks(), status_code=response.status_code, headers=headers)

    @app.websocket('/{path:path}')
    async def socket(client: WebSocket, path: str):
        if hardware_only:
            await client.close(code=1008)
            return
        if not trusted(client.headers, mutation=True):
            await client.close(code=1008)
            return
        origin, path = upstream('/'+path)
        if origin not in ('http://127.0.0.1:8000', 'http://127.0.0.1:6121'):
            await client.close(code=1008)
            return
        url = origin.replace('http:', 'ws:', 1)+path+('?' + client.url.query if client.url.query else '')
        protocols = [value.strip() for value in client.headers.get('sec-websocket-protocol', '').split(',') if value.strip()]
        try:
            async with websockets.connect(url, origin='http://127.0.0.1:4173', subprotocols=protocols or None,
                                          max_size=8*1024*1024, open_timeout=4) as server:
                await client.accept(subprotocol=server.subprotocol)

                async def outgoing():
                    while True:
                        item = await client.receive()
                        if item['type'] == 'websocket.disconnect':
                            return
                        await server.send(item.get('text') if item.get('text') is not None else item['bytes'])

                async def incoming():
                    async for item in server:
                        await (client.send_text(item) if isinstance(item, str) else client.send_bytes(item))
                jobs = [asyncio.create_task(outgoing()), asyncio.create_task(incoming())]
                try:
                    await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for job in jobs:
                        job.cancel()
                    await asyncio.gather(*jobs, return_exceptions=True)
        except (OSError, websockets.WebSocketException, WebSocketDisconnect, RuntimeError):
            try:
                await client.close(code=1011)
            except RuntimeError:
                pass
    return app


def from_environment():
    hardware = os.environ.get('NEIGHBOUR_HARDWARE_ONLY') == '1'
    origin = None
    if hardware:
        from edge_hub.cloud_primary import cloud_primary
        profile = cloud_primary(Path(__file__).resolve().parents[1])
        if profile is None or profile['phase'] != 'cloud':
            raise ValueError('Verified cloud primary required')
        origin = profile['origin']
    return create_gateway(os.environ['NEIGHBOUR_PROXY_TOKEN'], json.loads(os.environ['NEIGHBOUR_REMOTE_HOSTS']),
                          hardware_only=hardware, cloud_origin=origin, cloud_authorization=hardware)
