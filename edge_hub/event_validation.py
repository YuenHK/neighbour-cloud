"""Pure validation redaction; importing it never opens native services or EP."""
from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def redact_event_validation(request: Request, error: RequestValidationError):
    if request.url.path.startswith(('/api/v1/service-desk/', '/api/v1/resident/')):
        return JSONResponse({'detail': '請檢查必填內容及字數。'}, status_code=422,
                            headers={'Cache-Control': 'no-store'})
    if request.url.path.startswith('/api/v1/assistant/') or request.url.path == '/v1/chat/completions':
        return JSONResponse({'detail': 'assistant request failed validation'}, status_code=422,
                            headers={'Cache-Control': 'no-store'})
    if request.url.path == '/api/v1/robot' or request.url.path.startswith('/api/v1/robot/'):
        # Pydantic errors can include submitted lease credentials and private extras.
        return JSONResponse({'detail': 'robot request failed validation'}, status_code=422,
                            headers={'Cache-Control': 'no-store'})
    creating = request.method == 'POST' and request.url.path.rstrip('/') == '/api/v1/events'
    reviewing = (request.method == 'PATCH'
                 and getattr(request.scope.get('route'), 'path', None) == '/api/v1/events/{event_id}')
    if creating or reviewing:
        # Error inputs may contain private data or unpaired Unicode surrogates.
        return JSONResponse({'detail': 'event payload failed validation'}, status_code=422,
                            headers={'Cache-Control': 'no-store'})
    return await request_validation_exception_handler(request, error)

