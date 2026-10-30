import json
import sqlite3

import httpx
import pytest

from edge_hub import azure_voice


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(azure_voice, 'settings_root', lambda: tmp_path)
    monkeypatch.setattr(azure_voice, '_crypt', lambda *args, **kwargs: b'synthetic-key')
    (tmp_path / 'azure-speech-f0.json').write_text(json.dumps({'sku': 'F0', 'region': 'eastasia'}))
    (tmp_path / 'azure-speech-f0-key.dpapi').write_bytes(b'synthetic-ciphertext')
    return tmp_path


def test_compressed_transport_keeps_hiumaan_f0_and_only_one_reservation(prepared):
    calls = []

    def respond(request):
        calls.append(request)
        assert request.headers['x-microsoft-outputformat'] == 'audio-24khz-48kbitrate-mono-mp3'
        assert b'zh-HK-HiuMaanNeural' in request.content
        return httpx.Response(200, content=b'ID3' + b'public-fake-compressed-test' * 400)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        data = b''.join(azure_voice.mp3_chunks('公開測試', client=client))
    assert data.startswith(b'ID3') and len(calls) == 1
    with sqlite3.connect(prepared / 'cloud-usage.sqlite3') as db:
        assert db.execute('SELECT amount FROM usage WHERE meter=?', ('azure_tts_characters',)).fetchone()[0] == 8


def test_unrecognizable_compressed_body_is_rejected_without_retry(prepared):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=b'not-an-mp3')
    with (httpx.Client(transport=httpx.MockTransport(respond)) as client,
          pytest.raises(ValueError, match='invalid_mp3_stream')):
        list(azure_voice.mp3_chunks('公開測試', client=client))
    assert len(calls) == 1


def test_pause_prevents_compressed_request_and_preserves_usage(prepared):
    azure_voice.set_paused(True)
    with pytest.raises(ValueError, match='paused_or_limited'):
        list(azure_voice.mp3_chunks('公開測試', client=object()))
    assert not (prepared / 'cloud-usage.sqlite3').exists()
