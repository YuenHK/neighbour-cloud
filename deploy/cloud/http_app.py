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
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from deploy.cloud.bootstrap import CloudServices
from deploy.cloud.google_identity import (
    GoogleIdentityVerifier,
    IdentityUnavailable,
    InvalidIdentity,
)
from deploy.cloud.maintenance import CloudMaintenance
from deploy.cloud.photo_api import PHOTO_PATH, photo_router
from deploy.cloud.presentation import PUBLIC_PATH as PRESENTATION_PUBLIC_PATH
from deploy.cloud.presentation import STAFF_PATH as PRESENTATION_STAFF_PATH
from deploy.cloud.presentation import Presentation, PresentationEdit
from deploy.cloud.quota_api import QUOTA_PATH, CloudQuotas, quota_router
from deploy.cloud.robot_proxy import robot_path, robot_router
from deploy.cloud.site_access import PATH as ACCESS_PATH
from deploy.cloud.site_access import AccessInput, SiteSessions
from deploy.cloud.staff_api import staff_path, staff_router
from deploy.cloud.transcription_api import PATH as TRANSCRIPTION_PATH
from deploy.cloud.transcription_api import (
    CloudTranscriptionBodyLimit,
    Transcription,
    transcription_router,
)
from deploy.cloud.voice_api import STREAM_PATHS, CloudVoiceBodyLimit, voice_router
from deploy.cloud.web_assets import CloudWebAssets
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
    def __init__(self, app, services, verifier, origin, *, storage_acceptance=False, web_assets=None, maintenance=None, site_access=None):
        host = validate_origin(origin)
        self.app, self.services, self.verifier = app, services, verifier
        self.origin, self.host = origin, host
        self.storage_acceptance = storage_acceptance
        self.web_assets = web_assets or CloudWebAssets(governance=maintenance is not None)
        self.maintenance = maintenance
        self.site_access = site_access

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
        if method in ('GET', 'HEAD'):
            public = self.web_assets.response(path, storage_acceptance=self.storage_acceptance,
                                              client_id=self.verifier.client_id)
            if public is not None:
                if self.services.closed or not self.app.state.started:
                    return await reject(503, '服務暫時未能使用。')
                return await public(scope, receive, send)
        if self.storage_acceptance and method in ('GET', 'HEAD') and path in ('/', '/stage-login.js', '/login-config'):
            if self.services.closed or not self.app.state.started:
                return await reject(503, '服務暫時未能使用。')
            assets = Path(__file__).with_name('stage-login')
            if path == '/login-config':
                response = JSONResponse({'client_id': self.verifier.client_id})
            elif path == '/':
                response = HTMLResponse((assets / 'index.html').read_text(encoding='utf-8'))
            else:
                response = Response((assets / 'login.js').read_bytes(), media_type='text/javascript')
            response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Permissions-Policy': 'microphone=(), camera=(), autoplay=()',
                'Cross-Origin-Opener-Policy': 'same-origin-allow-popups',
                'Content-Security-Policy': "default-src 'none'; script-src 'self' https://accounts.google.com/gsi/client; "
                    "style-src 'unsafe-inline' https://accounts.google.com/gsi/style; "
                    "frame-src https://accounts.google.com/gsi/; connect-src 'self' https://accounts.google.com/gsi/; "
                    "img-src 'self' data: https://*.googleusercontent.com; frame-ancestors 'none'; base-uri 'none'"})
            return await response(scope, receive, send)
        if not (path.startswith(('/api/v1/resident/', '/api/v1/service-desk/'))
                or path == '/api/v1/events.csv' or path in STREAM_PATHS or PHOTO_PATH.fullmatch(path) or staff_path(path) or robot_path(path)
                or (self.maintenance is not None and path in ('/api/v1/governance/retention', '/api/v1/governance/audit'))):
            return await reject(404, '此雲端入口未提供這項功能。')
        if self.services.closed or not self.app.state.started:
            return await reject(503, '服務暫時未能使用。')
        if self.site_access is not None and path == ACCESS_PATH and method == 'POST':
            return await self.app(scope, receive, send)
        credentials = [v for k, v in headers if k.lower() == b'authorization']
        if (len(credentials) != 1 or not credentials[0].startswith(b'Bearer ')
                or not 8 <= len(credentials[0]) <= 16391):
            return await reject(401, '請先使用已核准的 Google 帳戶登入。')
        try:
            token = credentials[0][7:].decode('ascii')
            principal = await (self.site_access.verify(token)
                if self.site_access is not None and self.site_access.owns(token) else self.verifier.verify(token))
        except (InvalidIdentity, UnicodeError):
            return await reject(401, '登入憑證未獲接納，請重新登入。')
        except IdentityUnavailable:
            return await reject(503, '暫時未能核對登入身份，請稍後再試。')
        identity = _principal.set(principal)
        try:
            if self.storage_acceptance and method not in ('GET', 'HEAD'):
                return await reject(423, '正式資料尚未切換；目前只供核對登入及資料，未開放居民操作。')
            if self.maintenance is not None:
                if path == '/api/v1/governance/retention' and method == 'GET':
                    if principal.role != 'staff':
                        return await reject(403, '需要已核准的職員身份。')
                    # Only cached operational state: no SQL/audit writes while
                    # a coordinated maintenance snapshot owns the writer gate.
                    return await JSONResponse(self.maintenance.public_status(), headers={
                        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})(scope, receive, send)
                if not await self.maintenance.gate.enter():
                    return await JSONResponse({'detail': '系統正在整理服務資料，正在為你重新連接。',
                        'code': 'service_maintenance', 'operation_outcome': 'not_attempted'}, status_code=503,
                        headers={'Cache-Control': 'no-store'})(scope, receive, send)
            try:
                with self.services.scope():
                    await self.app(scope, receive, send)
            finally:
                if self.maintenance is not None:
                    await self.maintenance.gate.leave()
        finally:
            _principal.reset(identity)


def include_selected(app, router, prefixes):
    selected = APIRouter()
    selected.routes.extend(route for route in router.routes if getattr(route, 'path', '').startswith(prefixes))
    app.include_router(selected)


class CloudServiceBodyLimit(ServiceBodyLimitMiddleware):
    def matches(self, scope):
        return scope.get('path') != TRANSCRIPTION_PATH and super().matches(scope)


def create_app(services, verifier, *, origin, model_client=None, voice_client=None, quota_client=None,
               storage_acceptance=False, web_assets=None, maintenance=None, release_probe=None, site_access=None, presentation=None):
    if (not isinstance(services, CloudServices) or services.closed
            or not isinstance(verifier, GoogleIdentityVerifier) or type(storage_acceptance) is not bool):
        raise ValueError('explicit_open_cloud_services_and_google_verifier_required')
    if site_access is not None and (not isinstance(site_access, SiteSessions) or storage_acceptance):
        raise ValueError('explicit_formal_site_access_required')
    if presentation is not None and not isinstance(presentation, Presentation):
        raise ValueError('explicit_cloud_presentation_required')
    if maintenance is not None and (not isinstance(maintenance, CloudMaintenance)
            or maintenance.services is not services or storage_acceptance):
        raise ValueError('explicit_matching_formal_cloud_maintenance_required')
    if release_probe is not None and (maintenance is None or not callable(release_probe)):
        raise ValueError('formal_maintenance_required_for_release_acceptance')

    @asynccontextmanager
    async def lifespan(app):
        owned = model_client is None
        client = model_client or httpx.AsyncClient(trust_env=False, follow_redirects=False,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4, keepalive_expiry=60))
        async with AsyncExitStack() as cleanup:
            cleanup.callback(services.close)
            if site_access is not None:
                cleanup.callback(site_access.close)
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
            app.state.robot_client = httpx.AsyncClient(trust_env=False, follow_redirects=False,
                limits=httpx.Limits(max_connections=16, max_keepalive_connections=8, keepalive_expiry=30))
            cleanup.push_async_callback(app.state.robot_client.aclose)
            cleanup.push_async_callback(app.state.resident_transcription.close)
            if maintenance is not None:
                maintenance.scheduled = True

                def pending_work():
                    return [item['task'] for item in app.state.resident_transcription.entries.values()
                            if not item['task'].done()] + list(services.residents.search_pending.values())

                async def run_maintenance():
                    while not maintenance.gate.stopping:
                        delay = 3600
                        try:
                            await maintenance.cycle(pending_work, after=release_probe)
                        except (OSError, ValueError, RuntimeError, sqlite3.Error):
                            delay = 60  # Read/reconcile durable state; never reset a pending backup.
                        await asyncio.sleep(delay)

                maintenance_task = asyncio.create_task(run_maintenance())

                async def stop_maintenance():
                    maintenance.gate.stopping = True
                    maintenance_task.cancel()
                    try:
                        await maintenance_task
                    except asyncio.CancelledError:
                        pass
                    maintenance.scheduled = False

                cleanup.push_async_callback(stop_maintenance)
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
    app.state.resident_transcription = Transcription(lambda: app.state.resident_cloud_client)
    if presentation is not None:
        services.residents.runtime_settings = presentation.runtime

        @app.get('/api/v1/service-desk/airi-services')
        def airi_services():
            require_staff()
            from deploy.cloud.airi_runtime import catalog
            return catalog()

        @app.get(PRESENTATION_PUBLIC_PATH)
        def resident_presentation():
            return presentation.public()

        @app.get(PRESENTATION_STAFF_PATH)
        def staff_presentation():
            require_staff()
            return presentation.current(refresh=True)

        @app.put(PRESENTATION_STAFF_PATH)
        def save_presentation(payload: PresentationEdit):
            require_staff()
            return presentation.save(payload)
    if site_access is not None:
        @app.post(ACCESS_PATH)
        async def site_login(payload: AccessInput):
            result = await run_in_threadpool(site_access.resident if payload.password is None
                else lambda: site_access.login(payload.password))
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    app.include_router(timing_router(resident_request=verified_resident_request, timings=app.state.browser_timings))
    app.add_middleware(CloudServiceBodyLimit)
    app.add_middleware(CloudVoiceBodyLimit)
    app.add_middleware(CloudTranscriptionBodyLimit)
    app.include_router(transcription_router(app.state.resident_transcription, current_principal))

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
                   or request.url.path in ('/api/v1/events.csv', QUOTA_PATH, '/api/v1/governance/audit', PRESENTATION_STAFF_PATH) or staff_path(request.url.path))
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
        ready = (maintenance is not None and maintenance.state['last_success'] is True
                 and not maintenance.gate.blocked and not maintenance.gate.stopping)
        return JSONResponse({'status': 'ready' if ready else 'candidate', 'public_ready': ready, 'site_hardware': False},
                            status_code=503 if services.closed or not app.state.started else 200)

    @app.get('/api/v1/resident/session')
    def session():
        principal = current_principal()
        if principal is None:
            raise HTTPException(401)
        result = {'authenticated': True, 'role': principal.role, 'storage_acceptance': storage_acceptance}
        if maintenance is not None:
            result['governance_supported'] = True
        return result

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
                               resident_request=verified_resident_request, delivery_scope='cloud_staff_workbench_only',
                               resident_persona=presentation.prompt if presentation is not None else None)
    include_selected(app, desk, ('/api/v1/resident/', '/api/v1/service-desk/'))
    app.include_router(resident_adapter_router(resident_request=verified_resident_request, completion=strict_completion))
    include_selected(app, estate_router(services.estate, require_staff),
        ('/api/v1/service-desk/knowledge', '/api/v1/service-desk/resident-memories'))
    app.include_router(voice_router(lambda text: azure_voice.pcm_chunks(
        text, client=app.state.resident_voice_client), runtime=presentation.runtime if presentation is not None else None,
        options_chunks_factory=lambda text, options: azure_voice.pcm_chunks(
            text, client=app.state.resident_voice_client, options=options),
        staff_preview=lambda: current_principal() is not None and current_principal().role == 'staff'))
    app.include_router(photo_router(services, require_staff))
    app.include_router(staff_router(services, require_staff))
    app.include_router(robot_router(presentation, require_staff, lambda: app.state.robot_client))
    app.state.quotas = CloudQuotas(lambda: app.state.quota_client)
    app.include_router(quota_router(require_staff, app.state.quotas))

    if maintenance is not None:
        @app.get('/api/v1/governance/audit')
        def cloud_audit(limit: int = 50):
            require_staff()
            if type(limit) is not int or not 1 <= limit <= 100:
                raise HTTPException(422, '請選擇有效紀錄數目。')
            return {'items': services.journal.recent(limit)}

    @app.get('/api/v1/events.csv')
    def csv_export():
        require_staff()
        try:
            prepared = PreparedEventExport(services.events)
        except ExportPreparationError:
            return JSONResponse({'detail': 'event export temporarily unavailable'}, status_code=503)
        return StreamingResponse(prepared, media_type='text/csv',
            headers={'Content-Disposition': 'attachment; filename="events.csv"'}, background=BackgroundTask(prepared.close))

    return CloudBoundary(app, services, verifier, origin, storage_acceptance=storage_acceptance,
                         web_assets=web_assets, maintenance=maintenance, site_access=site_access)
