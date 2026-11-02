import asyncio
import base64

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from edge_hub import azure_voice
from edge_hub.browser_timing import browser_timings, timing_router
from local_audio_gateway.resident_stream import stream_router


class Body(BaseModel):
    model: str = azure_voice.MODEL
    voice: str = azure_voice.VOICE
    input: str
    speed: float = 1


def test_pcm_yields_before_completion_one_reservation_and_closes(tmp_path, monkeypatch):
    (tmp_path/'azure-speech-f0-key.dpapi').write_bytes(b'synthetic')
    reserves, seen = [], []
    monkeypatch.setattr(azure_voice, 'require_available', lambda: None)
    monkeypatch.setattr(azure_voice, 'settings_root', lambda: tmp_path)
    monkeypatch.setattr(azure_voice, '_crypt', lambda *a, **k: b'synthetic')
    monkeypatch.setattr(azure_voice.CloudAllowance, 'reserve', lambda self, data: reserves.append(data))
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            seen.append('first'); yield b'\0\0'*2048
            seen.append('last'); yield b'\0\0'*2048
        def close(self): seen.append('closed')
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,stream=Stream()))) as client:
        chunks = azure_voice.pcm_chunks('公開虛構句子', client=client)
        assert len(next(chunks)) == 4096
        assert seen == ['first'] and len(reserves) == 1
        chunks.close()
        assert seen[-1] == 'closed' and 'last' not in seen


def test_endpoint_cache_done_failure_and_no_other_voice(monkeypatch):
    calls=[]
    monkeypatch.setattr(azure_voice, 'require_available', lambda: None)
    def chunks(text):
        calls.append(text)
        if text == 'fail':
            raise ValueError('private details must not leak')
        yield b'\0\0'*16
    monkeypatch.setattr(azure_voice, 'pcm_chunks', chunks)
    app=FastAPI();app.include_router(stream_router(Body, lambda:{'tts_provider':'azure'}, lambda s:s))
    with TestClient(app) as client:
        for _ in range(2):
            result=client.post('/v1/audio/resident-stream',json={'input':'synthetic'})
            assert '"done":true' in result.text and base64.b64encode(b'\0\0'*16).decode() in result.text
        assert calls == ['synthetic']
        failure=client.post('/v1/audio/resident-stream',json={'input':'fail'})
        assert 'voice_unavailable' in failure.text and 'private' not in failure.text
        assert client.post('/v1/audio/resident-stream',json={'input':'x','voice':'other'}).status_code == 400


def test_browser_timing_local_only_fixed_fields_and_bounds():
    app=FastAPI();app.include_router(timing_router())
    with TestClient(app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',123)) as client:
        assert client.post('/api/v1/resident/timing',json={'marks':{'first_text':250.0}}).status_code==200
        assert client.post('/api/v1/resident/timing',json={'marks':{'cancelled':4500.0}}).status_code==200
        assert client.post('/api/v1/resident/timing',json={'marks':{'phone':250.0}}).status_code==422
        assert client.post('/api/v1/resident/timing',json={'marks':{'first_text':-1.0}}).status_code==422
        assert client.post('/api/v1/resident/timing',json={'marks':{'first_text':1.0}},headers={'Origin':'https://outside.invalid'}).status_code==403
    assert 'audio scheduled' in browser_timings.snapshot()['scope']


def test_early_body_close_explicitly_closes_retained_upstream_iterator(monkeypatch):
    class RetainedSource:
        closed = False
        def __iter__(self): return self
        def __next__(self): return b'\0\0' * 16
        def close(self): self.closed = True
    source = RetainedSource()
    monkeypatch.setattr(azure_voice, 'require_available', lambda: None)
    monkeypatch.setattr(azure_voice, 'pcm_chunks', lambda _: source)
    router = stream_router(Body, lambda: {'tts_provider': 'azure'}, lambda value: value)

    async def run():
        response = router.routes[0].endpoint(Body(input='synthetic'))
        assert 'audio' in await anext(response.body_iterator)
        await response.body_iterator.aclose()
    asyncio.run(run())
    assert source.closed


def test_bad_text_before_stream_registration_cannot_leak_both_slots(monkeypatch):
    monkeypatch.setattr(azure_voice, 'require_available', lambda: None)
    monkeypatch.setattr(azure_voice, 'pcm_chunks', lambda _: iter([b'\0\0' * 16]))
    router = stream_router(Body, lambda: {'tts_provider': 'azure'}, lambda value: value)
    endpoint = router.routes[0].endpoint

    async def run():
        for _ in range(2):
            try:
                response = endpoint(Body(input='\ud800'))
                await anext(response.body_iterator)
                await response.body_iterator.aclose()
            except (UnicodeEncodeError, HTTPException):
                pass
        response = endpoint(Body(input='valid-synthetic'))
        return ''.join([frame async for frame in response.body_iterator])
    assert '"done":true' in asyncio.run(run())


def test_asgi_send_disconnect_closes_upstream_before_response_is_discarded(monkeypatch):
    import pytest
    from starlette.requests import ClientDisconnect
    sources = []

    class Source:
        closed = False
        def __iter__(self): return self
        def __next__(self): return b'\0\0' * 16
        def close(self): self.closed = True

    def make(_):
        source = Source(); sources.append(source)
        return source
    monkeypatch.setattr(azure_voice, 'require_available', lambda: None)
    router = stream_router(Body, lambda: {'tts_provider': 'azure'}, lambda value: value, chunks_factory=make)

    async def run():
        response = router.routes[0].endpoint(Body(input='disconnect-synthetic'))
        async def receive():
            await asyncio.Event().wait()
        async def send(message):
            if message['type'] == 'http.response.body' and message.get('body'):
                raise OSError('client-disconnected')
        with pytest.raises(ClientDisconnect):
            await response({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send)
        assert sources[0].closed
        # Hold two replacement streams to prove cancellation returned its slot.
        replacements = [router.routes[0].endpoint(Body(input=f'replacement-{i}')) for i in range(2)]
        try:
            for item in replacements:
                assert 'audio' in await anext(item.body_iterator)
        finally:
            for item in replacements:
                await item.body_iterator.aclose()
    asyncio.run(run())
    assert all(source.closed for source in sources)


def test_failed_source_close_cannot_seed_cache_or_leak_capacity(monkeypatch):
    calls = []
    class Source:
        remaining = 1
        def __iter__(self): return self
        def __next__(self):
            if not self.remaining: raise StopIteration
            self.remaining -= 1
            return b'\0\0' * 16
        def close(self): raise OSError('PRIVATE-close-failure')

    def make(text):
        calls.append(text)
        return Source()
    monkeypatch.setattr(azure_voice, 'require_available', lambda: None)
    router = stream_router(Body, lambda: {'tts_provider': 'azure'}, lambda value: value, chunks_factory=make)

    async def run():
        for _ in range(3):
            response = router.routes[0].endpoint(Body(input='same-synthetic'))
            body = ''.join([frame async for frame in response.body_iterator])
            assert 'voice_unavailable' in body and '"done":true' not in body and 'PRIVATE' not in body
    asyncio.run(run())
    assert calls == ['same-synthetic'] * 3
