"""Retire old console pages without touching their records or control APIs."""
from fastapi.responses import RedirectResponse

RETIRED = {
    '/ep-preparation': '/robots',
    '/ep-acceptance': '/robots',
    '/ep-idle-acceptance': '/robots',
    '/ep-short-press-acceptance': '/robots',
    '/ep-release-check-acceptance': '/robots',
    '/ep-idle-motor-acceptance': '/robots',
    '/ep-manual-pairing': '/robots',
    '/simulation-control': '/admin#work',
    '/assistant-memory': '/admin#knowledge',
    '/residents': '/',
}


def install_retired_pages(app):
    @app.middleware('http')
    async def retired_pages(request, call_next):
        if request.method in ('GET', 'HEAD') and request.url.path in RETIRED:
            return RedirectResponse(RETIRED[request.url.path], status_code=307,
                                    headers={'Cache-Control': 'no-store'})
        return await call_next(request)
