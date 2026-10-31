"""Loopback-only, same-origin gateway behind an authenticated ngrok endpoint.

The edge must perform Google OAuth + exact email allowlisting and inject a
fresh random hop secret after removing any client-supplied copy. This server
never exposes the existing unauthenticated loopback services on its own.
"""
import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse

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


def create_gateway(secret, hosts, *, transport=None, hardware_only=False):
    if not isinstance(secret, str) or len(secret) < 32 or not secret.isascii():
        raise ValueError('A fresh edge hop secret is required')
    hosts = frozenset(hosts)
    if not hosts or any(not isinstance(host, str) or '/' in host or ':' in host for host in hosts):
        raise ValueError('Exact remote hosts are required')

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
        return (authorized and host in hosts
                and (not mutation or headers.get('origin') == 'https://'+host))

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    async def proxy(request: Request, path: str):
        if not trusted(request.headers, mutation=request.method not in ('GET', 'HEAD', 'OPTIONS')):
            return JSONResponse({'detail': '請透過已登入的鄰伴遠端入口使用。'}, status_code=403,
                                headers={'Cache-Control': 'no-store'})
        path = '/'+path
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
            # The authenticated OAuth edge is the sole remote caller. Preserve
            # native loopback policy; client-supplied fetch metadata is not proof.
            forwarded['sec-fetch-site'] = 'same-origin'
        try:
            outgoing = app.state.proxy.build_request(request.method, url, headers=forwarded, content=bytes(body))
            response = await app.state.proxy.send(outgoing, stream=True)
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
    return create_gateway(os.environ['NEIGHBOUR_PROXY_TOKEN'], json.loads(os.environ['NEIGHBOUR_REMOTE_HOSTS']),
                          hardware_only=os.environ.get('NEIGHBOUR_HARDWARE_ONLY') == '1')
