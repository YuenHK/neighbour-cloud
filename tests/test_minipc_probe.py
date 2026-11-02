import io
import json
import wave

import httpx
import pytest

from tools.probe_minipc import probe


@pytest.mark.parametrize('receipt', [True, False])
def test_live_probe_scope_and_receipt_are_truthful(tmp_path, receipt):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    (runtime / 'operator-key.txt').write_text('secret-test-key')
    wav_bytes = io.BytesIO()
    with wave.open(wav_bytes, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b'\0\0' * 100)
    calls = []

    def respond(request):
        assert request.url.host == '127.0.0.1'
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path == '/health':
            return httpx.Response(200, json={'status': 'ok', 'tts_engine': 'vits-cantonese',
                'conversation': {'version': 2, 'automatic_chat_storage': False,
                                 'paired_chat_route': 'local_ollama_only', 'web_search_enabled': False}})
        if path in ('/admin', '/ep-preparation', '/assistant-memory'):
            return httpx.Response(200, text='<html></html>')
        if path == '/api/v1/robot/ep/preparation':
            from edge_hub.ep_preparation import preparation_status
            return httpx.Response(200, json=preparation_status(),
                                  headers={'Cache-Control': 'no-store'})
        if path == '/v1/chat/completions':
            if json.loads(request.content)['stream']:
                return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"測試"}}]}\n\ndata: [DONE]\n')
            return httpx.Response(200, json={'choices': [{'message': {'content': '測試'}}]})
        if path == '/v1/audio/speech':
            return httpx.Response(200, content=wav_bytes.getvalue())
        assert path == '/api/v1/events' and request.method == 'POST'
        payload = json.loads(request.content)
        assert payload['details'] == {'is_test': True, 'source': 'software_validation'}
        assert payload['type'] == 'temperature_drill'
        (runtime / 'airi-bridge-events.log').write_text(payload['id'] + '\n')
        if receipt:
            (runtime / 'airi-bridge-receiver-completions.log').write_text(payload['id'] + '\n')
        return httpx.Response(201, json=payload)

    result = probe(root=tmp_path, transport=httpx.MockTransport(respond), receipt_timeout=0)
    assert result['all_checks_passed'] is receipt
    assert result['checks']['event_delivery']['receiver_completion'] is receipt
    assert result['checks']['event_delivery']['authenticated_or_durable_ack'] is False
    assert result['ep_contacted'] is result['microphone_used'] is result['playback_verified'] is False
    assert calls.count(('POST', '/api/v1/events')) == 1
    assert calls.count(('POST', '/v1/audio/speech')) == 3
    assert not any('/connect' in path or '/command' in path for _, path in calls)
    assert 'secret-test-key' not in json.dumps(result)


def test_probe_redacts_failures_and_does_not_retry(tmp_path):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    (runtime / 'operator-key.txt').write_text('secret-test-key')
    calls = []

    def fail(request):
        calls.append(request.url.path)
        raise httpx.ConnectError('secret-test-key must not appear')

    report = probe(root=tmp_path, transport=httpx.MockTransport(fail), receipt_timeout=0)
    assert report['all_checks_passed'] is False
    assert calls.count('/api/v1/events') == 1
    assert report['checks']['event_delivery']['creation_outcome'] == 'unknown_no_retry'
    assert 'secret-test-key' not in json.dumps(report)
