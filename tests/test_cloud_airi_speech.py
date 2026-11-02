
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deploy.cloud.airi_runtime import AiriRuntime
from deploy.cloud.voice_api import voice_router
from edge_hub import azure_voice


def test_airi_prosody_preserves_default_voice_and_escapes_text():
    assert azure_voice.speech_xml('你好') == ('<speak version="1.0" xml:lang="zh-HK">'
        '<voice name="zh-HK-HiuMaanNeural">你好</voice></speak>').encode()
    xml = azure_voice.speech_xml('<voice name="paid">', {'rate': .9, 'pitch': 3., 'volume': -2.})
    assert b'rate="0.9"' in xml and b'pitch="+3%"' in xml and b'volume="-2%"' in xml
    assert b'&lt;voice' in xml and b'<voice name="paid"' not in xml
    for options in ({'rate': 10}, {'rate': float('nan')}, {'pitch': True}, {'voice': 'paid'}):
        with pytest.raises(ValueError):
            azure_voice.speech_xml('公開測試', options)


def test_saved_airi_voice_and_staff_preview_share_pipeline_but_not_wrong_style_cache(monkeypatch):
    monkeypatch.setattr(azure_voice, 'require_available', lambda: None)
    preferences = AiriRuntime().model_dump()
    calls = []
    staff = [False]
    def chunks(text, options):
        calls.append((text, dict(options)))
        yield b'\0\0' * 10
    app = FastAPI()
    app.include_router(voice_router(lambda text: (), runtime=lambda: preferences,
        options_chunks_factory=chunks, staff_preview=lambda: staff[0]))
    body = {'input': '公開設定測試'}
    with TestClient(app) as client:
        assert '"done":true' in client.post('/v1/audio/resident-stream', json=body).text
        assert '"done":true' in client.post('/v1/audio/resident-stream', json=body).text
        assert len(calls) == 1
        preferences['speech']['rate'] = .9
        client.post('/v1/audio/resident-stream', json=body)
        assert len(calls) == 2 and calls[-1][1]['rate'] == .9
        preview = {**body, 'preview': {'rate': 1.1, 'pitch': 2., 'volume': 0.}}
        assert client.post('/v1/audio/resident-stream', json=preview).status_code == 403
        assert len(calls) == 2
        staff[0] = True
        client.post('/v1/audio/resident-stream', json=preview)
        assert calls[-1][1]['rate'] == 1.1 and preferences['speech']['rate'] == .9
