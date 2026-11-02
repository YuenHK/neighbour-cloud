"""Staff-only fixed onsite robot relay. No SDK, new keys, data store or retry."""
import re
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse, Response

PREFIX = '/api/v1/robot/ep/'
ROOT_ACTIONS = 'fleet|qr|connection|connect|disconnect|cancel-pairing|lease|stop|prepare-control|command|reset-stop|discovery|delivery'
DEVICE_ACTIONS = (r'frame\.jpg|connection|video-frame|connect|disconnect|prepare-control|lease|stop|command|'
                  'video-start|video-stop|gimbal-start|gimbal-follow|gimbal-target|gimbal-stop|speed|'
                  'manual-warning|infrared-warning|check-stop|reset-stop|patrol')
PATH = re.compile(re.escape(PREFIX) + '(?:' + ROOT_ACTIONS + '|devices/[A-Za-z0-9_-]{1,60}(?:/(?:' + DEVICE_ACTIONS + '))?)')


def robot_path(path):
    return PATH.fullmatch(path) is not None


def robot_router(presentation, authorize, client_getter):
    router = APIRouter()

    @router.api_route(PREFIX + '{rest:path}', methods=['GET', 'POST', 'DELETE'])
    async def proxy(request: Request, rest: str):
        authorize()
        path = PREFIX + rest
        if not robot_path(path) or presentation is None:
            raise HTTPException(404, '未提供此機械人操作。')
        endpoint = presentation.current().get('robot_remote_url', '')
        if not re.fullmatch(r'https://[a-z0-9-]+\.ngrok-free\.(app|dev)', endpoint):
            raise HTTPException(503, '現場連接程式尚未設定。')
        query = dict(request.query_params)
        if query and (set(query) != {'after'} or not path.endswith('/frame.jpg')
                      or not re.fullmatch(r'[A-Za-z0-9_-]{0,64}', query['after'])):
            raise HTTPException(422, '請核對機械人查詢。')
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > 16384:
                raise HTTPException(413)
        headers = {'Authorization': request.headers['authorization'], 'Origin': str(request.base_url).rstrip('/'),
                   'Content-Type': 'application/json'}
        started = time.monotonic()
        try:
            client = client_getter()
            outgoing = client.build_request(request.method, endpoint + path, params=query, content=bytes(body), headers=headers,
                                            timeout=httpx.Timeout(25, connect=4, pool=2))
            response = await client.send(outgoing, stream=True, follow_redirects=False)
            try:
                if 300 <= response.status_code < 400:
                    raise HTTPException(503, '現場連接程式需要更新，未轉送控制指令。')
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 1024 * 1024:
                        raise HTTPException(502, '現場回覆未能核對。')
                result_headers = {name: value for name, value in response.headers.items()
                                  if name.lower() in {'content-type', 'x-frame-state', 'x-frame-key', 'x-frame-age-ms'}}
                if path.endswith('/frame.jpg') and response.status_code == 200:
                    age = int(result_headers.get('x-frame-age-ms', '1200')) + round((time.monotonic() - started) * 1000)
                    result_headers['x-frame-age-ms'] = str(age)
                    if age >= 1200:
                        result_headers['x-frame-state'] = 'stale'
                        return Response(status_code=204, headers=result_headers)
                return Response(bytes(content), status_code=response.status_code, headers=result_headers)
            finally:
                await response.aclose()
        except (httpx.HTTPError, ValueError):
            return JSONResponse({'detail': '現場連接暫時中斷，請留意現場情況。沒有自動重送指令。',
                                 'operation_outcome': 'read_unavailable' if request.method == 'GET' else 'unknown',
                                 'retry_policy': 'manual_review'}, status_code=503)

    return router
