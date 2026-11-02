import io
import wave

import httpx
import pytest

from tools import probe_local_audio


def test_probe_uses_only_fixed_text_and_rejected_audio(monkeypatch):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b'\0\0' * 100)
    paths = []

    def respond(request):
        paths.append(request.url.path)
        assert request.url.host == '127.0.0.1'
        if request.url.path == '/health':
            return httpx.Response(200, json={'tts_engine': 'vits-cantonese'})
        if request.url.path == '/v1/audio/speech':
            return httpx.Response(200, content=output.getvalue())
        assert request.url.path == '/v1/audio/transcriptions'
        assert b'not audio' in request.content
        return httpx.Response(400)

    client = httpx.Client(transport=httpx.MockTransport(respond), base_url='http://127.0.0.1:8765')
    monkeypatch.setattr(probe_local_audio.httpx, 'Client', lambda **kwargs: client)
    result = probe_local_audio.probe()
    assert paths.count('/v1/audio/speech') == 3
    assert paths.count('/v1/audio/transcriptions') == 1
    assert result['microphone_used'] is False
    assert result['playback_verified'] is False
    assert result['cloud_recognition_verified'] is False


def test_probe_refuses_alternate_tts_provider(monkeypatch):
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'tts_engine': 'unexpected-cloud'})),
        base_url='http://127.0.0.1:8765')
    monkeypatch.setattr(probe_local_audio.httpx, 'Client', lambda **kwargs: client)
    with pytest.raises(RuntimeError, match='no alternate provider'):
        probe_local_audio.probe()
