import base64
import io
import json
import wave

import httpx
import pytest

from edge_hub import gemini_voice
from edge_hub.cloud_allowance import AllowanceExceeded


def audio_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as output:
        output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        output.writeframes(b'\0\0'*240)
    return buffer.getvalue()


@pytest.fixture
def isolated_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_voice, 'settings_root', lambda: tmp_path)
    monkeypatch.setattr(gemini_voice, '_crypt', lambda data, **kwargs: b'public-synthetic-key')
    (tmp_path/'gemini-voice-key.dpapi').write_bytes(b'synthetic-encrypted')
    return tmp_path


def test_voice_uses_selected_youthful_voice_real_audio_and_only_supplied_text(isolated_voice):
    sent = []
    def respond(request):
        sent.append(json.loads(request.content))
        assert request.headers['x-goog-api-key'] == 'public-synthetic-key'
        return httpx.Response(200, json={'steps': [{'type': 'model_output', 'content': [{'type': 'audio', 'data': base64.b64encode(audio_bytes()).decode()}]}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert gemini_voice.synthesize('公開合成測試：你好。', 'Leda', client=client) == audio_bytes()
        assert not client.is_closed
    assert sent[0]['model'] == 'gemini-3.8-flash-lite-tts'
    assert sent[0]['generation_config']['speech_config'] == [{'voice': 'Leda'}]
    assert sent[0]['input'][0]['content'][0]['text'] == '公開合成測試：你好。'


def test_quota_failures_are_not_retried_or_switched_to_paid_models(isolated_voice):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(429, json={'error': {'status': 'RESOURCE_EXHAUSTED'}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, pytest.raises(httpx.HTTPStatusError):
        gemini_voice.synthesize('公開測試', client=client)
    assert len(calls) == 1


def test_local_reservation_refuses_dispatch_after_limit(isolated_voice, monkeypatch):
    def refuse(self, amounts):
        raise AllowanceExceeded('synthetic limit')
    monkeypatch.setattr(gemini_voice.CloudAllowance, 'reserve', refuse)
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail('must not dispatch'))) as client, pytest.raises(AllowanceExceeded):
        gemini_voice.synthesize('公開測試', client=client)


def test_invalid_generated_audio_is_not_returned_to_browser(isolated_voice):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'steps': [{'type': 'model_output', 'content': [{'type': 'audio', 'data': base64.b64encode(b'not audio').decode()}]}]}))) as client, pytest.raises(ValueError):
        gemini_voice.synthesize('公開測試', client=client)


def test_designed_hong_kong_voice_uses_persisted_id_and_hk_style(isolated_voice):
    (isolated_voice/'gemini-hk-voice.json').write_text(json.dumps({'id': 'voice_synthetic123'}))
    def respond(request):
        sent = json.loads(request.content)
        assert sent['generation_config']['speech_config'] == [{'voice': 'voice_synthetic123'}]
        assert 'yue-HK' in sent['input'][0]['content'][0]['annotations'][0]['style']
        return httpx.Response(200, json={'steps': [{'type': 'model_output', 'content': [{'type': 'audio', 'data': base64.b64encode(audio_bytes()).decode()}]}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert gemini_voice.synthesize('公開測試', 'HKSoft', client=client) == audio_bytes()


def test_invalid_designed_voice_refuses_network(isolated_voice):
    (isolated_voice/'gemini-hk-voice.json').write_text(json.dumps({'id': 'Leda'}))
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail('must not dispatch'))) as client, pytest.raises(ValueError, match='invalid_designed_voice'):
        gemini_voice.synthesize('公開測試', 'HKSoft', client=client)
