"""Bound selected event and robot POST buffering before FastAPI JSON decoding."""
import asyncio
import math

from starlette.responses import JSONResponse


def check_event_json_depth(body, max_depth=32):
    # This is only a structural-depth guard. Syntax/type validation remains with
    # the normal JSON parser and IngestEvent; braces inside strings are ignored.
    try:
        text = body.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise ValueError('event JSON must use UTF-8') from error
    if '\x00' in text:
        raise ValueError('event JSON must not contain raw NUL bytes')
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '{[':
            depth += 1
            if depth > max_depth:
                raise ValueError('event JSON exceeds nesting limit')
        elif char in '}]':
            depth -= 1


class EventBodyLimitMiddleware:
    label = 'event'

    def __init__(self, app, max_bytes=65536, timeout_seconds=5., max_depth=32):
        if (type(max_bytes) is not int or not 1 <= max_bytes <= 1024 * 1024
                or isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30
                or type(max_depth) is not int or not 1 <= max_depth <= 128):
            raise ValueError(f'invalid {self.label} request budget')
        self.app, self.max_bytes, self.timeout = app, max_bytes, timeout_seconds
        self.max_depth = max_depth

    def matches(self, scope):
        return (scope['type'] == 'http' and scope.get('method') == 'POST'
                and scope.get('path', '').rstrip('/') == '/api/v1/events')

    async def __call__(self, scope, receive, send):
        if not self.matches(scope):
            return await self.app(scope, receive, send)

        async def reject(status, detail):
            await JSONResponse({'detail': detail}, status_code=status,
                               headers={'Cache-Control': 'no-store'})(scope, receive, send)

        lengths = [value for name, value in scope.get('headers', []) if name.lower() == b'content-length']
        if len(lengths) > 1 or (lengths and not lengths[0].isdigit()):
            return await reject(400, f'invalid {self.label} content length')
        if lengths and (len(lengths[0]) > 10 or int(lengths[0]) > self.max_bytes):
            return await reject(413, f'{self.label} request body exceeds limit')
        body = bytearray()
        rejection = None
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return
                    if message['type'] != 'http.request':
                        rejection = (400, f'invalid {self.label} request stream')
                        break
                    chunk = message.get('body', b'')
                    if len(chunk) > self.max_bytes - len(body):
                        rejection = (413, f'{self.label} request body exceeds limit')
                        break
                    body.extend(chunk)
                    if not message.get('more_body', False):
                        break
                    # Even immediately available empty frames must let cancellation
                    # and the total receive deadline run; do not spin synchronously.
                    await asyncio.sleep(0)
        except TimeoutError:
            return await reject(408, f'{self.label} request body timed out')
        if rejection:
            return await reject(*rejection)  # Sending is outside the receive deadline.
        try:
            check_event_json_depth(body, self.max_depth)
        except ValueError as error:
            # Only this local guard's fixed messages are translated, never body content.
            return await reject(400, str(error).replace('event JSON', f'{self.label} JSON', 1))

        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()  # Preserve real disconnects; never synthesize an empty-body busy loop.
            replayed = True
            return {'type': 'http.request', 'body': bytes(body), 'more_body': False}

        await self.app(scope, replay, send)


class RobotBodyLimitMiddleware(EventBodyLimitMiddleware):
    label = 'robot'

    def __init__(self, app, max_bytes=8192, timeout_seconds=1., max_depth=16):
        super().__init__(app, max_bytes, timeout_seconds, max_depth)

    def matches(self, scope):
        path = scope.get('path', '')
        return (scope['type'] == 'http' and scope.get('method') == 'POST'
                and (path == '/api/v1/robot' or path.startswith('/api/v1/robot/')))
