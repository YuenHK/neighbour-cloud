import io
import json
import wave

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from edge_hub import azure_voice
from edge_hub.cloud_allowance import CloudAllowance


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(azure_voice, 'settings_root', lambda: tmp_path)
    monkeypatch.setattr(azure_voice, '_crypt', lambda value, **kwargs: b'fake-key')
    (tmp_path/'azure-speech-f0.json').write_text(json.dumps({'sku': 'F0', 'region': 'eastasia'}))
    (tmp_path/'azure-speech-f0-key.dpapi').write_bytes(b'fake-encrypted')
    return tmp_path


def test_cjk_double_count_including_extension_and_plain_text():
    assert azure_voice.billable_characters('你好A，𠀀') == 8


def test_f0_required_before_any_request(prepared):
    (prepared/'azure-speech-f0.json').write_text(json.dumps({'sku': 'S0', 'region': 'eastasia'}))
    with pytest.raises(ValueError):
        azure_voice.synthesize('你好', client=object())


def test_pause_survives_and_cannot_reset_quota(prepared):
    CloudAllowance(prepared/'cloud-usage.sqlite3').reserve({'azure_tts_characters': 400000})
    azure_voice.set_paused(True)
    assert azure_voice.status()['paused']
    state = azure_voice.set_paused(False)
    assert state['used'] == 400000 and state['blocked']
    with pytest.raises(ValueError):
        azure_voice.synthesize('你好', client=object())


def test_corrupt_pause_control_fails_closed(prepared):
    (prepared/'azure-voice-control.json').write_text('{broken')
    assert azure_voice.status()['blocked']


def test_exact_voice_xml_escape_and_reserve_before_dispatch(prepared):
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b'\0\0'*240)

    def handler(request):
        assert request.url.host == 'eastasia.tts.speech.microsoft.com'
        assert azure_voice.status()['used'] == 4
        body = request.content.decode()
        assert 'zh-HK-HiuMaanNeural' in body and '你&lt;&amp;' in body
        return httpx.Response(200, content=audio.getvalue())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert azure_voice.synthesize('你<&', client=client) == audio.getvalue()


def test_provider_error_never_retries_or_falls_back(prepared):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(httpx.HTTPStatusError):
        azure_voice.synthesize('你好', client=client)
    assert len(calls) == 1 and azure_voice.status()['used'] == 4


def test_private_contact_and_unit_never_leave_in_tts_ssml(prepared):
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(b'\0\0'*240)
    calls = []
    def handler(request):
        body = request.content.decode()
        calls.append(body)
        assert '91234567' not in body and '12樓' not in body and '已隱去' not in body
        assert '你提及嘅單位' in body and 'zh-HK-HiuMaanNeural' in body
        return httpx.Response(200, content=audio.getvalue())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        azure_voice.synthesize('A座12樓B室，電話91234567，已轉交職員。', client=client)
    assert len(calls) == 1


def test_control_requires_operator_and_rejects_billing_fields(prepared):
    def authorize(key):
        if key != 'test-operator':
            raise HTTPException(403)

    app = FastAPI()
    app.include_router(azure_voice.control_router(authorize))
    with TestClient(app) as client:
        url = '/api/v1/service-desk/voice-control'
        assert client.put(url, json={'paused': True}).status_code == 403
        headers = {'X-Operator-Key': 'test-operator'}
        assert client.put(url, headers=headers, json={'paused': True, 'sku': 'S0'}).status_code == 422
        assert client.put(url, headers=headers, json={'paused': 'false'}).status_code == 422
        assert client.put(url, headers=headers, json={'paused': True}).json()['paused']
        assert client.get(url, headers=headers).json()['automatic_paid_upgrade'] is False
