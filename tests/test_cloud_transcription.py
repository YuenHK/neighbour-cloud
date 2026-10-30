import base64
import io
import json
import struct
import wave
from contextlib import closing
from datetime import UTC, datetime

import httpx
import pytest
import test_cloud_http_app

from deploy.cloud import transcription_api
from edge_hub.cloud_allowance import CloudAllowance

prepared = test_cloud_http_app.prepared
seeded = test_cloud_http_app.seeded
keys = test_cloud_http_app.keys
api = test_cloud_http_app.api
PATH = '/api/v1/resident/transcription'


def audio(seconds=1, value=100):
    target = io.BytesIO()
    with wave.open(target, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack('<h', value) * int(16000 * seconds))
    return target.getvalue()


def body(raw=None, *, session='a', identifier='b'):
    return {'session_id': session * 32, 'input_id': identifier * 32,
            'audio': base64.b64encode(raw if raw is not None else audio()).decode('ascii')}


def used(api):
    with api.services.scope():
        path = api.services.storage.settings_root / 'cloud-usage.sqlite3'
        with closing(api.services.storage.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            return db.execute('SELECT COALESCE(SUM(amount),0) FROM usage WHERE meter=? AND period=?',
                              ('cloudflare_gemma_neuron_reservations', datetime.now(UTC).strftime('%Y-%m-%d'))).fetchone()[0]


@pytest.fixture
def recognizer(api, monkeypatch):
    from edge_hub import cloudflare_gemma
    root = api.services.storage.settings_root
    (root / 'cloudflare-whisper-free.json').write_text(json.dumps({
        'enabled': True, 'user_approved': True, 'model': transcription_api.MODEL, 'plan': 'Free'}))
    monkeypatch.setattr(cloudflare_gemma, 'configuration', lambda: {'account_id': 'c' * 32})
    monkeypatch.setattr(cloudflare_gemma, '_crypt', lambda *a, **kw: b'synthetic-cloudflare-only-key')
    (root / 'cloudflare-gemma-key.dpapi').write_bytes(b'synthetic-reference')
    requests, status, text = [], [200], ['你好呀，今日想同你傾吓。']

    def respond(request):
        requests.append(request)
        assert request.url == 'https://api.cloudflare.com/client/v4/accounts/' + 'c' * 32 + '/ai/run/' + transcription_api.MODEL
        assert request.headers['authorization'] == 'Bearer synthetic-cloudflare-only-key'
        assert 'X-Operator-Key' not in request.headers
        data = json.loads(request.content)
        assert data['task'] == 'transcribe' and data['language'] == 'yue'
        assert 'translate' not in request.content.decode()
        return httpx.Response(status[0], json={'success': status[0] == 200, 'result': {'text': text[0]}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    api.app.app.state.resident_transcription.client_override = client
    yield api, requests, status, text
    api.app.app.state.resident_transcription.client_override = None
    import asyncio
    asyncio.run(client.aclose())


def test_whisper_uses_shared_reservation_and_reuses_identical_input_in_same_session(recognizer):
    api, requests, _, _ = recognizer
    before = used(api)
    for _ in range(2):
        response = api.client.post(PATH, headers=api.resident, json=body())
        assert response.status_code == 200 and response.json()['text'] == '你好呀，今日想同你傾吓。'
        assert response.json()['engine'] == 'cloudflare-whisper-free'
    assert len(requests) == 1 and used(api) == before + 1
    assert not (api.services.storage.settings_root / 'cloud-usage.sqlite3').exists()


def test_auth_or_invalid_audio_does_not_call_provider_or_reserve(recognizer):
    api, requests, _, _ = recognizer
    before = used(api)
    assert api.client.post(PATH, headers={'Origin': test_cloud_http_app.ORIGIN}, json=body()).status_code == 401
    for changed in ({**body(), 'model': 'paid-model'}, {**body(), 'audio': 'http://PRIVATE.invalid/audio.wav'},
                    body(b'PRIVATE-NOT-A-WAV'), body(audio(46)), {**body(), 'input_id': 'PRIVATE'}):
        response = api.client.post(PATH, headers=api.resident, json=changed)
        assert response.status_code in (400, 422) and 'PRIVATE' not in response.text
    assert requests == [] and used(api) == before


def test_exact_silence_is_empty_without_spending_and_changed_audio_same_id_conflicts(recognizer):
    api, requests, _, _ = recognizer
    before = used(api)
    response = api.client.post(PATH, headers=api.resident, json=body(audio(value=0)))
    assert response.status_code == 200 and response.json()['text'] == '' and not requests
    assert used(api) == before
    assert api.client.post(PATH, headers=api.resident, json=body()).status_code == 200
    assert api.client.post(PATH, headers=api.resident, json=body(audio(value=101))).status_code == 409
    assert len(requests) == 1


def test_unknown_ack_is_not_automatically_retried_or_refunded(recognizer):
    api, requests, status, _ = recognizer
    before = used(api)
    status[0] = 503
    first = api.client.post(PATH, headers=api.resident, json=body())
    second = api.client.post(PATH, headers=api.resident, json=body())
    assert first.status_code == second.status_code == 503
    assert used(api) == before + 1 and len(requests) == 1


def test_rate_limit_blocks_shared_provider_and_keeps_reservation(recognizer):
    api, requests, status, _ = recognizer
    status[0] = 429
    before = used(api)
    assert api.client.post(PATH, headers=api.resident, json=body()).status_code == 429
    assert api.client.post(PATH, headers=api.resident, json=body(identifier='d')).status_code == 503
    assert len(requests) == 1 and used(api) == before + 1
    assert api.services.storage.controls.read('cloudflare-gemma-cooldown.json')['reason'] == 'rate_limit'


def test_explicit_consent_configuration_and_budget_are_required(recognizer):
    api, requests, _, _ = recognizer
    root = api.services.storage.settings_root
    (root / 'cloudflare-whisper-free.json').write_text('{}')
    assert api.client.post(PATH, headers=api.resident, json=body()).status_code == 503
    (root / 'cloudflare-whisper-free.json').write_text(json.dumps({
        'enabled': True, 'user_approved': True, 'model': transcription_api.MODEL, 'plan': 'Free'}))
    before = used(api)
    with api.services.scope():
        CloudAllowance(root / 'cloud-usage.sqlite3').reserve({'cloudflare_gemma_neuron_reservations': 8000 - before})
    assert api.client.post(PATH, headers=api.resident, json=body(identifier='e')).status_code == 429
    assert requests == [] and used(api) == 8000


def test_full_45_second_turn_is_allowed_without_weakening_other_json_limits(recognizer):
    api, requests, _, _ = recognizer
    before = used(api)
    response = api.client.post(PATH, headers=api.resident, json=body(audio(45)))
    assert response.status_code == 200 and len(requests) == 1 and used(api) == before + 39
    assert api.client.post('/api/v1/resident/chat', headers=api.resident, content='x' * 65537).status_code == 413
    assert api.client.post(PATH, headers=api.resident, content='x' * (2 * 1024 * 1024 + 1)).status_code == 413


def test_different_identity_or_resident_session_does_not_receive_previous_cached_transcript(recognizer):
    api, requests, _, text = recognizer
    assert api.client.post(PATH, headers=api.resident, json=body()).status_code == 200
    text[0] = '另一段公開測試。'
    response = api.client.post(PATH, headers=api.staff, json=body())
    assert response.status_code == 200 and response.json()['text'] == text[0]
    assert api.client.post(PATH, headers=api.resident, json=body(session='f')).status_code == 200
    assert len(requests) == 3
