"""Bounded resident-only PCM SSE endpoint; never a provider fallback."""
import base64
import hashlib
import json
import threading
from collections import OrderedDict

from anyio import CancelScope
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from edge_hub import azure_voice


class OwnedStreamResponse(StreamingResponse):
    def __init__(self, source, **kwargs):
        async def frames():
            try:
                async for frame in iterate_in_threadpool(source):
                    yield frame
            finally:
                with CancelScope(shield=True):
                    await run_in_threadpool(source.close)
        super().__init__(frames(), **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with CancelScope(shield=True):
                await self.body_iterator.aclose()


def stream_router(body_type, profile, spoken, *, chunks_factory=None):
    if chunks_factory is not None and not callable(chunks_factory):
        raise TypeError('voice_chunks_factory_required')
    router = APIRouter()
    slots = threading.BoundedSemaphore(2)
    lock = threading.Lock()
    active = set()
    cache = OrderedDict()

    def endpoint(body):
        if (profile().get('tts_provider') != 'azure' or body.model != azure_voice.MODEL
                or body.voice != azure_voice.VOICE or body.speed != 1):
            raise HTTPException(400, '居民串流只使用曉曼F0原速。')
        try:
            text = spoken(body.input)
            if not isinstance(text, str) or not text.strip() or len(text) > 1500:
                raise ValueError('invalid_voice_text')
            identity = hashlib.sha256(azure_voice.spoken_private(text).encode()).hexdigest()
        except (UnicodeError, ValueError, TypeError):
            raise HTTPException(400, '語音文字不正確或太長。') from None

        def generate():
            if not slots.acquire(blocking=False):
                yield 'data: {"error":"busy"}\n\n'
                return
            registered = False
            source = None

            def close_source():
                nonlocal source
                previous, source = source, None
                close = getattr(previous, 'close', None)
                if callable(close):
                    close()

            try:
                azure_voice.require_available()
                with lock:
                    if identity in active:
                        raise ValueError('duplicate_in_flight')
                    active.add(identity)
                    registered = True
                    cached = cache.get(identity)
                chunks = []
                size = 0
                provider = azure_voice.pcm_chunks if chunks_factory is None else chunks_factory
                source = iter(cached if cached is not None else provider(text))
                for chunk in source:
                    size += len(chunk)
                    if size <= 2_000_000:
                        chunks.append(chunk)
                    yield 'data: '+json.dumps({'audio': base64.b64encode(chunk).decode()})+'\n\n'
                close_source()
                if cached is None and size <= 2_000_000:
                    with lock:
                        cache[identity] = tuple(chunks)
                        while len(cache) > 24 or sum(sum(map(len, value)) for value in cache.values()) > 12_000_000:
                            cache.popitem(last=False)
                yield 'data: {"done":true}\n\n'
            except Exception:  # noqa: BLE001 -- never expose credentials or upstream response text
                yield 'data: {"error":"voice_unavailable"}\n\n'
            finally:
                try:
                    close_source()
                finally:
                    if registered:
                        with lock:
                            active.discard(identity)
                    slots.release()
        return OwnedStreamResponse(generate(), media_type='text/event-stream', headers={'Cache-Control':'no-store','X-Voice-Engine':'azure-hiumaan-f0'})
    endpoint.__annotations__['body'] = body_type
    router.add_api_route('/v1/audio/resident-stream', endpoint, methods=['POST'])
    return router
