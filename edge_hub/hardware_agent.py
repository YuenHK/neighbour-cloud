"""Hardware-only loopback console after the resident data moved to the cloud.

Creates no resident/event/quota stores. Merely starting this app starts no SDK,
discovery thread, camera or robot connection. Existing EP workers and their
audit/deadman/lease protections are used only for explicit console requests.
"""
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from edge_hub.cloud_primary import cloud_primary
from edge_hub.ep_console import ep_console_router
from edge_hub.ep_fleet import EpFleetBroker
from edge_hub.local_operator import LOCAL_OPERATOR_TOKEN, local_console_request, operator_page

STATIC = Path(__file__).with_name('static')


def create_agent(root=None, *, broker=None, delivery=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    profile = cloud_primary(root)
    if profile is None or profile['phase'] != 'cloud':
        raise RuntimeError('hardware_agent_requires_cloud_primary')
    broker = broker if broker is not None else EpFleetBroker(root)
    credential = root / '.runtime/patrol-delivery.dpapi'
    if delivery is None and credential.is_file():
        from edge_hub.patrol_delivery import PatrolDelivery
        delivery = PatrolDelivery.load(root / '.runtime/patrol-outbox', profile['origin'], credential)
    patrol = None
    if delivery is not None:
        from edge_hub.ep_patrol import EpPatrol
        patrol = EpPatrol(broker.patrol_frame, delivery, root / '.runtime/patrol-outbox',
                          context_source=broker.patrol_context, arm_context=broker.arm_patrol_context)
        broker.patrol = patrol
        original_snapshot = broker.fleet_snapshot
        def delivery_snapshot():
            return {**original_snapshot(), 'delivery': delivery.status()}
        broker.fleet_snapshot = delivery_snapshot

    @asynccontextmanager
    async def lifespan(app):
        yield
        if patrol is not None:
            patrol.close()
            delivery.close()
        # close() only closes already running workers; never starts a worker.
        broker.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def authorize(key):
        if not isinstance(key, str) or not hmac.compare_digest(key, LOCAL_OPERATOR_TOKEN):
            raise HTTPException(403, '請由本機或已登入的機械人控制台操作。')

    @app.middleware('http')
    async def boundary(request, call_next):
        if not local_console_request(request):
            return JSONResponse({'detail': '請由現場控制台或已核准的安全遠端入口操作。'}, status_code=403)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                                 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                                 'Permissions-Policy': 'microphone=(), camera=()'})
        return response

    @app.get('/health')
    def health():
        return {'status': 'ok', 'mode': 'hardware-only', 'resident_writer': False, 'automatic_connection': False}

    @app.get('/')
    @app.get('/robots')
    def console(request: Request):
        page = operator_page((STATIC / 'ep-fleet.html').read_text(encoding='utf-8'), request)
        # Hardware-only stays manual for connection; delivery readiness is a
        # separate capability, never a reason to auto-connect a discovered EP.
        page = page.replace('data-ep-ui="fleet"', 'data-ep-ui="fleet" data-hardware-only="true"')
        # No global auto-connection script, resident API or duplicate data writer.
        page = page.replace('<script src="/assets/service/ep-background.js" defer></script>', '')
        page = page.replace('href="/admin#caseHeading"', 'href="' + profile['origin'] + '/"')
        page = page.replace('href="/admin"', 'href="' + profile['origin'] + '/"')
        page = page.replace('href="/"', 'href="' + profile['origin'] + '/"')
        page = page.replace('>居民求助 ', '>雲端管理 ')
        return HTMLResponse(page)

    @app.get('/assets/service-shell.css')
    def styles():
        return Response((STATIC / 'service-shell.css').read_bytes(), media_type='text/css')

    @app.get('/assets/service/service-mark.svg')
    def mark():
        return Response((STATIC / 'service-mark.svg').read_bytes(), media_type='image/svg+xml')

    @app.post('/api/v1/robot/ep/devices/{device_id}/patrol')
    async def configure_patrol(device_id: str, request: Request, x_operator_key: str | None = Header(default=None)):
        authorize(x_operator_key)
        if patrol is None:
            raise HTTPException(409, '現場回報尚未配對；現可手動查看鏡頭及控制機體。')
        from edge_hub.ep_patrol import PatrolSettings
        settings = PatrolSettings.model_validate(await request.json())
        if settings.cloud_review:
            raise HTTPException(422, '此回報通道只用本機初步辨識，再由職員核實；未啟用額外雲端視覺。')
        return patrol.configure(device_id, settings)

    @app.get('/api/v1/robot/ep/delivery')
    def delivery_status(x_operator_key: str | None = Header(default=None)):
        authorize(x_operator_key)
        return delivery.status() if delivery is not None else {'state': 'not_paired', 'resident_writer': False}

    app.include_router(ep_console_router(broker, authorize, STATIC))
    app.state.broker = broker
    app.state.patrol = patrol
    return app
