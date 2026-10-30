"""Short, session-scoped replay of completed turns; never cache partial replies."""
import hashlib
import json
import re
import time
from collections import OrderedDict

from fastapi import HTTPException
from fastapi.responses import StreamingResponse


class TurnReplay:
    def __init__(self):
        self.completed = OrderedDict()
        self.pending = set()

    def key(self, headers, payload):
        ids = [headers.get(name, '') for name in ('x-resident-session', 'x-resident-turn')]
        if not all(re.fullmatch('[a-f0-9]{32}', value) for value in ids):
            return None
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return (*ids, digest)

    def begin(self, key):
        if key is None:
            return None
        now = time.monotonic()
        for expired in [identity for identity, item in self.completed.items() if item[0] <= now]:
            del self.completed[expired]
        cached = self.completed.get(key)
        if cached:
            async def replay():
                yield cached[1]
            return StreamingResponse(replay(), media_type='text/event-stream', headers={'Cache-Control': 'no-store'})
        if key in self.pending or len(self.pending) >= 8:
            raise HTTPException(409, '本輪正在處理，未重複送出。')
        self.pending.add(key)
        return None

    def wrap(self, key, response):
        if key is None:
            return response
        if not isinstance(response, StreamingResponse):
            self.pending.discard(key)
            return response

        async def record():
            body = bytearray()
            try:
                async for piece in response.body_iterator:
                    data = piece.encode() if isinstance(piece, str) else piece
                    body.extend(data)
                    yield data
                # Only an acknowledged terminal packet, never a partial/error, can be replayed.
                if (len(body) <= 65536 and b'data: [DONE]' in body
                        and b'"refusal"' not in body and b'"error"' not in body):
                    self.completed[key] = (time.monotonic()+180, bytes(body))
                    while len(self.completed) > 32:
                        self.completed.popitem(last=False)
            finally:
                self.pending.discard(key)
                await response.body_iterator.aclose()
        return StreamingResponse(record(), headers=dict(response.headers), background=response.background)
