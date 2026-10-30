"""Opt-in Google free-tier Cantonese speech; no billing changes or retries."""
import base64
import binascii
import io
import json
import re
import wave

import httpx

from edge_hub.cloud_allowance import CloudAllowance
from edge_hub.cloud_credentials import _crypt, settings_root

MODEL = 'gemini-3.8-flash-lite-tts'
VOICES = {'Leda', 'Zephyr', 'HKSoft'}
HK_STYLE_REVISION = 'hk-warm-v2'
HK_STYLE = ('Speak as a youthful young-adult Hong Kong woman having a warm, personal conversation with one neighbour. '
            'Use authentic everyday Hong Kong Cantonese (yue-HK), native vowels and tones, without a Mandarin accent. '
            'Sound gently smiling, tender, friendly and interested, with light youthful brightness, never shrill. '
            'Use fluid connected phrases and varied, natural pitch contours rather than evenly stressed words or flat reading. '
            'Give a brief soft pause between ideas; use a gently inviting question ending and a warm, reassuring finish. '
            'For worries, soften sincerely and leave space; for greetings, sound quietly delighted to meet them. '
            'Keep a relaxed fluent conversational pace, not slow word-by-word speech, whispering, singing or a service announcement. '
            'Read exactly the supplied words without adding any words.')
STYLE = ('Native Hong Kong Cantonese. A cute youthful feminine character voice, warm, bright, '
         'naturally expressive and gently energetic. Conversational, never a newsreader or squeaky. '
         'When acknowledging worries, soften sincerely and calmly rather than sounding excited. '
         'Read only the supplied words, do not add anything or sing.')


def configured():
    return (settings_root()/'gemini-voice-key.dpapi').is_file()


def synthesize(text, voice='Leda', speed=1.0, *, client=None):
    if voice not in VOICES or not 0 < len(text) <= 1500:
        raise ValueError('invalid_voice_input')
    key = _crypt((settings_root()/'gemini-voice-key.dpapi').read_bytes(), decrypt=True).decode()
    voice_id = voice
    if voice == 'HKSoft':
        voice_id = json.loads((settings_root()/'gemini-hk-voice.json').read_text(encoding='utf-8'))['id']
        if not isinstance(voice_id, str) or not re.fullmatch(r'voice_[A-Za-z0-9_-]{8,128}', voice_id):
            raise ValueError('invalid_designed_voice')
    CloudAllowance(settings_root()/'cloud-usage.sqlite3').reserve({
        'gemini_tts_requests': 1, 'gemini_tts_characters': len(text)})
    payload = {'model': MODEL, 'input': [{'type': 'user_input', 'content': [{'type': 'text',
        'text': text, 'annotations': [{'type': 'speech_metadata', 'style': (HK_STYLE if voice == 'HKSoft' else STYLE)+f' Pace: {speed:.2f} times normal.'}]}]}],
        'response_format': {'type': 'audio'}, 'generation_config': {'speech_config': [{'voice': voice_id}]}}
    owned = client is None
    client = client or httpx.Client(timeout=10, follow_redirects=False)
    try:
        response = client.post('https://generativelanguage.googleapis.com/v1beta/interactions',
                               headers={'x-goog-api-key': key}, json=payload)
        response.raise_for_status()
        if len(response.content) > 30_000_000:
            raise ValueError('voice_response_too_large')
        try:
            audio = [part for step in response.json().get('steps', []) if step.get('type') == 'model_output'
                     for part in step.get('content', []) if part.get('type') == 'audio']
            if not audio:
                raise ValueError('no_generated_audio')
            data = base64.b64decode(audio[-1]['data'], validate=True)
            with wave.open(io.BytesIO(data), 'rb') as wav:
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or not 8000 <= wav.getframerate() <= 48000 or not 0 < wav.getnframes()/wav.getframerate() <= 120:
                    raise ValueError('invalid_generated_audio')
        except (KeyError, TypeError, AttributeError, binascii.Error, wave.Error, EOFError) as exc:
            raise ValueError('invalid_generated_audio') from exc
        return data
    finally:
        if owned:
            client.close()
