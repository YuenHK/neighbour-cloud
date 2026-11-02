import io
import wave
from types import SimpleNamespace

import pytest

from tools.benchmark_audio_conversation import measure_local


def fake_wav():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0' * 320)
    return buffer.getvalue()


def test_local_benchmark_separates_cache_attempts_without_audio_or_text_in_report():
    calls = []
    def synthesize(request):
        calls.append(request.input)
        return SimpleNamespace(body=fake_wav(), headers={
            'x-tts-engine': 'vits-cantonese',
            'x-tts-cache': 'miss' if len(calls) % 2 else 'hit',
        })
    result = measure_local(synthesize, SimpleNamespace, ('reviewed text',))
    assert calls == ['reviewed text', 'reviewed text']
    assert result['expected_vits_and_cache_pattern']
    assert not result['audio_written_by_benchmark'] and not result['cloud_called']
    assert not result['complete_voice_acceptance']
    assert 'reviewed text' not in str(result)
    assert result['results'][0]['audio_seconds'] == .01


def test_empty_or_fallback_audio_cannot_claim_expected_neural_result():
    def fallback(request):
        return SimpleNamespace(body=fake_wav(), headers={'x-tts-engine': 'espeak-ng-fallback'})
    assert not measure_local(fallback, SimpleNamespace, ('test',))['expected_vits_and_cache_pattern']
    def broken(request):
        return SimpleNamespace(body=b'', headers={})
    with pytest.raises(EOFError):
        measure_local(broken, SimpleNamespace, ('test',))
