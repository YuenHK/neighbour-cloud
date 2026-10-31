"""Hardware-only loopback console after the resident data moved to the cloud.

Creates no resident/event/quota stores. Merely starting this app starts no SDK,
discovery thread, camera or robot connection. Existing EP workers and their
audit/deadman/lease protections are used only for explicit console requests.
"""
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from edge_hub.cloud_primary import cloud_primary
from edge_hub.ep_console import ep_console_router
from edge_hub.ep_fleet import EpFleetBroker
from edge_hub.local_operator import LOCAL_OPERATOR_TOKEN, local_console_request, operator_page

STATIC = Path(__file__).with_name('static')


def create_agent(root=None, *, broker=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    profile = cloud_primary(root)
    if profile is None or profile['phase'] != 'cloud':
        raise RuntimeError('hardware_agent_requires_cloud_primary')
    broker = broker if broker is not None else EpFleetBroker(root)

    @asynccontextmanager
    async def lifespan(app):
        yield
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
    def patrol(request: Request):
        # Do not silently fork event/case data back into the retired local DB.
        raise HTTPException(409, '自動巡查回報尚未接通雲端；現可手動查看鏡頭及控制機體。')

    app.include_router(ep_console_router(broker, authorize, STATIC))
    app.state.broker = broker
    return app
