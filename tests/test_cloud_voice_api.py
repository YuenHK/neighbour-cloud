import base64
import json

import httpx
import pytest
import test_cloud_http_app

pytest.importorskip('jwt', reason='optional cloud authentication research dependency')
prepared = test_cloud_http_app.prepared
seeded = test_cloud_http_app.seeded
keys = test_cloud_http_app.keys
api = test_cloud_http_app.api


@pytest.fixture
def speech(api, monkeypatch):
    from edge_hub import azure_voice

    root = api.services.storage.settings_root
    (root / 'azure-speech-f0.json').write_text(json.dumps({'sku': 'F0', 'region': 'eastasia'}))
    (root / 'azure-speech-f0-key.dpapi').write_bytes(b'synthetic-key-reference-only')
    monkeypatch.setattr(azure_voice, '_crypt', lambda *a, **kw: b'synthetic-voice-key')
    api.services.storage.controls.write('azure-voice-control.json', {'paused': False})
    requests, trace, status = [], [], [200]

    class Audio(httpx.SyncByteStream):
        def __iter__(self):
            trace.append('first'); yield b'\0\0' * 2048
            trace.append('last'); yield b'\0\0' * 2048
        def close(self):
            trace.append('closed')

    def respond(request):
        requests.append(request)
        assert request.url.host == 'eastasia.tts.speech.microsoft.com'
        assert request.headers['Ocp-Apim-Subscription-Key'] == 'synthetic-voice-key'
        assert request.headers['X-Microsoft-OutputFormat'] == 'raw-24khz-16bit-mono-pcm'
        assert 'authorization' not in request.headers
        assert 'zh-HK-HiuMaanNeural' in request.content.decode()
        return httpx.Response(status[0], stream=Audio())

    client = httpx.Client(transport=httpx.MockTransport(respond))
    api.app.app.state.resident_voice_client = client
    try:
        yield api, requests, trace, status
    finally:
        client.close()


def request_body(text='公開句子'):
    return {'input': text, 'model': 'azure-hiumaan-f0', 'voice': 'zh-HK-HiuMaanNeural', 'speed': 1}


def used(api):
    from edge_hub.azure_voice import status
    with api.services.scope():
        return status()['used']


def test_authenticated_pcm_and_alias_share_cache_and_one_persisted_f0_reservation(speech):
    api, requests, trace, _ = speech
    path = '/v1/audio/resident-stream'
    before = used(api)
    for target in (path, '/_audio' + path):
        response = api.client.post(target, headers=api.resident, json=request_body())
        assert response.status_code == 200 and response.headers['x-voice-engine'] == 'azure-hiumaan-f0'
        frames = [json.loads(part.removeprefix('data: ')) for part in response.text.strip().split('\n\n')]
        assert frames[-1] == {'done': True}
        assert b''.join(base64.b64decode(part['audio']) for part in frames[:-1]) == b'\0\0' * 4096
    assert len(requests) == 1 and used(api) == before + 8
    assert trace == ['first', 'last', 'closed']
    assert not (api.services.storage.settings_root / 'cloud-usage.sqlite3').exists()


def test_voice_auth_strict_input_and_format_do_not_dispatch_or_spend(speech):
    api, requests, _, _ = speech
    path = '/v1/audio/resident-stream'
    before = used(api)
    assert api.client.post(path, json=request_body()).status_code == 403  # Missing same-origin mutation.
    assert api.client.post(path, headers={'Origin': 'https://neighbour.example'}, json=request_body()).status_code == 401
    for changes in ({'model': 'local'}, {'voice': 'other'}, {'speed': 1.5}):
        assert api.client.post(path, headers=api.resident, json={**request_body(), **changes}).status_code == 400
    for changes in ({'api_key': 'NEVER-ACCEPT'}, {'input': 'x' * 1501}, {'input': '\x00'}, {'response_format': 'mp3'}):
        assert api.client.post(path, headers=api.resident, json={**request_body(), **changes}).status_code == 422
    assert api.client.post(path, headers=api.resident, content='x' * 8193).status_code == 413
    assert requests == [] and used(api) == before


def test_pause_or_guard_limit_stops_even_cached_audio_without_reset(speech):
    from edge_hub.cloud_allowance import CloudAllowance

    api, requests, _, _ = speech
    path = '/v1/audio/resident-stream'
    assert '"done":true' in api.client.post(path, headers=api.resident, json=request_body()).text
    before = used(api)
    api.services.storage.controls.write('azure-voice-control.json', {'paused': True})
    paused = api.client.post(path, headers=api.resident, json=request_body())
    assert 'voice_unavailable' in paused.text and used(api) == before
    api.services.storage.controls.write('azure-voice-control.json', {'paused': False})
    with api.services.scope():
        CloudAllowance(api.services.storage.settings_root / 'cloud-usage.sqlite3').reserve(
            {'azure_tts_characters': 400000 - before})
    limited = api.client.post(path, headers=api.resident, json=request_body())
    assert 'voice_unavailable' in limited.text and used(api) == 400000
    assert len(requests) == 1


def test_upstream_failure_is_not_cached_refunded_or_retried(speech):
    api, requests, _, status = speech
    status[0] = 429
    before = used(api)
    response = api.client.post('/v1/audio/resident-stream', headers=api.resident, json=request_body())
    assert 'voice_unavailable' in response.text and '"done":true' not in response.text
    assert len(requests) == 1 and used(api) == before + 8
    status[0] = 200
    # A distinct manual retry is allowed; the failed attempt did not seed cache.
    retry = api.client.post('/v1/audio/resident-stream', headers=api.resident, json=request_body())
    assert '"done":true' in retry.text and len(requests) == 2 and used(api) == before + 16


def test_same_hiumaan_speech_masks_private_contact_without_forwarding_login(speech):
    api, requests, _, _ = speech
    response = api.client.post('/v1/audio/resident-stream', headers=api.resident,
                               json=request_body('A座12樓B室，電話91234567，已轉交職員。'))
    assert '"done":true' in response.text
    ssml = requests[0].content.decode()
    assert '91234567' not in ssml and '12樓' not in ssml and '已隱去' not in ssml
    assert '你提及嘅單位' in ssml and 'authorization' not in requests[0].headers
