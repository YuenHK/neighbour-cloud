"""Unpublished, hardware-free authenticated API candidate, not a full cloud UI.

No default app/server or auth enrolment. Callers must provision a real Google
OAuth audience and pinned subjects, and pass already opened CloudServices.
The native app/loopback rules are unchanged. No EP/WebSocket or local model.
"""
import asyncio
import re
import sqlite3
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, StreamingResponse

from deploy.cloud.bootstrap import CloudServices
from deploy.cloud.google_identity import (
    GoogleIdentityVerifier,
    IdentityUnavailable,
    InvalidIdentity,
)
from deploy.cloud.photo_api import PHOTO_PATH, photo_router
from deploy.cloud.quota_api import QUOTA_PATH, CloudQuotas, quota_router
from deploy.cloud.voice_api import STREAM_PATHS, CloudVoiceBodyLimit, voice_router
from edge_hub import azure_voice, cloudflare_gemma
from edge_hub.browser_timing import BrowserTimings, timing_router
from edge_hub.csv_export import ExportPreparationError, PreparedEventExport
from edge_hub.estate_services import estate_router
from edge_hub.governance import private_staff_path
from edge_hub.resident_adapter import resident_adapter_router
from edge_hub.resident_cloud import CloudUnavailable
from edge_hub.resident_inference import RESIDENT_LOCAL_PROMPT
from edge_hub.resident_models import GEMMA_MODEL
from edge_hub.service_desk import ServiceBodyLimitMiddleware, service_desk_router

_principal = ContextVar('cloud_verified_principal', default=None)


def current_principal():
    return _principal.get()


def require_staff(_ignored_client_key=None):
    principal = current_principal()
    if principal is None or principal.role != 'staff':
        raise HTTPException(403, '需要已核准的職員身份。')


def verified_resident_request(_request):
    return current_principal() is not None


def storage_failure(request, *, not_attempted=False):
    """A missing DB acknowledgement never proves a mutation was rolled back."""
    if not_attempted:
        outcome, policy = 'not_attempted', 'manual_retry'
        message = '查閱紀錄暫時未能保存，這次操作尚未執行。'
    elif request.method in ('GET', 'HEAD', 'OPTIONS'):
        outcome, policy = 'read_unavailable', 'manual_retry'
        message = '暫時未能讀取資料，請稍後再查看。'
    else:
        outcome, policy = 'unknown', 'review_before_retry'
        message = '暫時未能確認保存結果，請先核對現有資料。'
        if request.method == 'POST' and request.url.path == '/api/v1/service-desk/requests':
            policy = 'same_submission_id_same_content'
            message = '未能確認求助單是否收妥；請保留原內容，重試時沿用同一次傳送。'
        elif request.method == 'PATCH' and request.url.path.startswith('/api/v1/service-desk/requests/'):
            policy = 'read_current_revision'
            message = '未能確認更新結果，請重新查看個案狀態後再處理。'
    return JSONResponse({'detail': message, 'code': 'storage_unavailable',
        'operation_outcome': outcome, 'retry_policy': policy}, status_code=503,
        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


def validate_origin(origin):
    if not isinstance(origin, str):
        raise TypeError('exact_https_cloud_origin_required')
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.port is not None or parsed.path or parsed.query or parsed.fragment
            or not parsed.hostname.isascii() or not re.fullmatch(r'[a-z0-9.-]{1,253}', parsed.hostname)
            or any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-')
                   for label in parsed.hostname.split('.')) or origin != 'https://' + parsed.hostname):
        raise ValueError('exact_https_cloud_origin_required')
    return parsed.hostname


class CloudBoundary:
    def __init__(self, app, services, verifier, origin):
        host = validate_origin(origin)
        self.app, self.services, self.verifier = app, services, verifier
        self.origin, self.host = origin, host

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.app(scope, receive, send)
        if scope['type'] == 'websocket':
            return await send({'type': 'websocket.close', 'code': 1008})
        if scope['type'] != 'http':
            return

        async def reject(status, message):
            await JSONResponse({'detail': message}, status_code=status, headers={
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})(scope, receive, send)

        headers = scope.get('headers', [])
        hosts = [v for k, v in headers if k.lower() == b'host']
        origins = [v for k, v in headers if k.lower() == b'origin']
        if (scope.get('scheme') != 'https' or hosts != [self.host.encode('ascii')]
                or len(origins) > 1 or (origins and origins != [self.origin.encode('ascii')])):
            return await reject(403, '請使用已核准的安全入口。')
        path, method = scope.get('path', ''), scope.get('method', '')
        if method not in ('GET', 'HEAD', 'OPTIONS') and not origins:
            return await reject(403, '請從同一個服務頁面操作。')
        if path == '/health' and method in ('GET', 'HEAD'):
            return await self.app(scope, receive, send)
        if not (path.startswith(('/api/v1/resident/', '/api/v1/service-desk/'))
                or path == '/api/v1/events.csv' or path in STREAM_PATHS or PHOTO_PATH.fullmatch(path)):
            return await reject(404, '此雲端入口未提供這項功能。')
        if self.services.closed or not self.app.state.started:
            return await reject(503, '服務暫時未能使用。')
        credentials = [v for k, v in headers if k.lower() == b'authorization']
        if (len(credentials) != 1 or not credentials[0].startswith(b'Bearer ')
                or not 8 <= len(credentials[0]) <= 16391):
            return await reject(401, '請先使用已核准的 Google 帳戶登入。')
        try:
            principal = await self.verifier.verify(credentials[0][7:].decode('ascii'))
        except (InvalidIdentity, UnicodeError):
            return await reject(401, '登入憑證未獲接納，請重新登入。')
        except IdentityUnavailable:
            return await reject(503, '暫時未能核對登入身份，請稍後再試。')
        identity = _principal.set(principal)
        try:
            with self.services.scope():
                await self.app(scope, receive, send)
        finally:
            _principal.reset(identity)


def include_selected(app, router, prefixes):
    selected = APIRouter()
    selected.routes.extend(route for route in router.routes if getattr(route, 'path', '').startswith(prefixes))
    app.include_router(selected)


def create_app(services, verifier, *, origin, model_client=None, voice_client=None, quota_client=None):
    if (not isinstance(services, CloudServices) or services.closed
            or not isinstance(verifier, GoogleIdentityVerifier)):
        raise ValueError('explicit_open_cloud_services_and_google_verifier_required')

    @asynccontextmanager
    async def lifespan(app):
        owned = model_client is None
        client = model_client or httpx.AsyncClient(trust_env=False, follow_redirects=False,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4, keepalive_expiry=60))
        async with AsyncExitStack() as cleanup:
            cleanup.callback(services.close)
            cleanup.push_async_callback(verifier.aclose)
            if owned:
                cleanup.push_async_callback(client.aclose)
            voice = voice_client or httpx.Client(trust_env=False, follow_redirects=False, timeout=15,
                limits=httpx.Limits(max_connections=2, max_keepalive_connections=2, keepalive_expiry=120))
            if voice_client is None:
                cleanup.callback(voice.close)
            quota = quota_client or httpx.AsyncClient(trust_env=False, follow_redirects=False,
                limits=httpx.Limits(max_connections=2, max_keepalive_connections=2, keepalive_expiry=60))
            if quota_client is None:
                cleanup.push_async_callback(quota.aclose)
            app.state.resident_cloud_client = client
            app.state.resident_voice_client = voice
            app.state.quota_client = quota
            app.state.started = True
            try:
                yield
            finally:
                app.state.started = False
                tasks = list(services.residents.search_pending.values())
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.started = False
    app.state.browser_timings = BrowserTimings()
    app.include_router(timing_router(resident_request=verified_resident_request, timings=app.state.browser_timings))
    app.add_middleware(ServiceBodyLimitMiddleware)
    app.add_middleware(CloudVoiceBodyLimit)

    @app.exception_handler(RequestValidationError)
    async def validation(_request, _error):
        return JSONResponse({'detail': '請檢查必填內容及字數。'}, status_code=422,
                            headers={'Cache-Control': 'no-store'})

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def unavailable_storage(request, _error):
        # No SQL, paths, keys, request bodies or exception strings in a reply.
        return storage_failure(request)

    @app.middleware('http')
    async def audit(request: Request, call_next):
        private = (private_staff_path(request.url.path, request.method)
                   or request.url.path in ('/api/v1/events.csv', QUOTA_PATH))
        identity = None
        if private:
            try:
                identity = await run_in_threadpool(services.journal.begin, request.method, request.url.path,
                                                  'cloud_' + current_principal().role)
            except (OSError, sqlite3.Error):
                return storage_failure(request, not_attempted=True)
        try:
            response = await call_next(request)
        except BaseException:
            if identity is not None:
                try:
                    await run_in_threadpool(services.journal.finish, identity, 500)
                except (OSError, sqlite3.Error):
                    pass  # Keep the durable unfinished intent and original error.
            raise
        if identity is not None:
            try:
                await run_in_threadpool(services.journal.finish, identity, response.status_code)
            except (OSError, sqlite3.Error):
                pass  # Durable intent remains; do not misreport a committed write.
        if request.url.path != '/health':
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/health')
    def health():
        return JSONResponse({'status': 'candidate', 'public_ready': False, 'site_hardware': False},
                            status_code=503 if services.closed or not app.state.started else 200)

    async def strict_completion(payload, *, prompt, context='', client=None, model=GEMMA_MODEL):
        if model != GEMMA_MODEL:
            raise CloudUnavailable('fixed_gemma_only')
        return await cloudflare_gemma.complete(payload, prompt=prompt, context=context, client=client)

    async def chat(payload):
        if payload.get('_local_only'):
            raise HTTPException(503, '這段私人記憶的雲端對話仍待驗證，未轉交其他模型。')
        try:
            return await strict_completion(payload, prompt=RESIDENT_LOCAL_PROMPT,
                context=payload.get('_service_context', ''), client=app.state.resident_cloud_client)
        except CloudUnavailable:
            raise HTTPException(503, 'Gemma 暫時未能回覆，未轉用其他模型。') from None

    static = Path(__file__).resolve().parents[2] / 'edge_hub/static'
    desk = service_desk_router(services.cases, require_staff, static, chat, services.residents,
                               resident_request=verified_resident_request, delivery_scope='cloud_staff_workbench_only')
    include_selected(app, desk, ('/api/v1/resident/', '/api/v1/service-desk/'))
    app.include_router(resident_adapter_router(resident_request=verified_resident_request, completion=strict_completion))
    include_selected(app, estate_router(services.estate, require_staff),
        ('/api/v1/service-desk/knowledge', '/api/v1/service-desk/resident-memories'))
    app.include_router(voice_router(lambda text: azure_voice.pcm_chunks(
        text, client=app.state.resident_voice_client)))
    app.include_router(photo_router(services, require_staff))
    app.state.quotas = CloudQuotas(lambda: app.state.quota_client)
    app.include_router(quota_router(require_staff, app.state.quotas))

    @app.get('/api/v1/events.csv')
    def csv_export():
        require_staff()
        try:
            prepared = PreparedEventExport(services.events)
        except ExportPreparationError:
            return JSONResponse({'detail': 'event export temporarily unavailable'}, status_code=503)
        return StreamingResponse(prepared, media_type='text/csv',
            headers={'Content-Disposition': 'attachment; filename="events.csv"'}, background=BackgroundTask(prepared.close))

    return CloudBoundary(app, services, verifier, origin)
