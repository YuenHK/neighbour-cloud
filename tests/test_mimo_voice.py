import base64
import io
import json
import wave
from unittest.mock import patch

import httpx
import pytest

from edge_hub import mimo_voice


def test_fixed_free_model_and_bingtang_tags_no_other_provider(tmp_path):
    (tmp_path/'mimo-voice-trial-key.dpapi').write_bytes(b'encrypted')
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(bytes(4800))
    calls = []
    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert str(request.url) == 'https://api.xiaomimimo.com/v1/chat/completions'
        assert body['model'] == 'mimo-v2.5-tts'
        assert body['audio'] == {'format': 'wav', 'voice': '冰糖'}
        assert body['messages'][1]['content'] == '(粤语 温柔 甜美)你好'
        return httpx.Response(200, json={'choices': [{'message': {'audio': {'data': base64.b64encode(out.getvalue()).decode()}}}]})
    with patch.object(mimo_voice, 'settings_root', return_value=tmp_path), patch.object(mimo_voice, '_crypt', return_value=b'test-key'), httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert mimo_voice.synthesize('你好', client=client) == out.getvalue()
    assert len(calls) == 1


def test_failure_is_not_retried_and_invalid_audio_rejected(tmp_path):
    (tmp_path/'mimo-voice-trial-key.dpapi').write_bytes(b'encrypted')
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429)
    with patch.object(mimo_voice, 'settings_root', return_value=tmp_path), patch.object(mimo_voice, '_crypt', return_value=b'test-key'), httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(httpx.HTTPStatusError):
        mimo_voice.synthesize('你好', client=client)
    assert len(calls) == 1
