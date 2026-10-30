"""Only the verified, currently free MiMo TTS model. Never falls back or retries."""
import base64
import io
import wave

import httpx

from edge_hub.cloud_credentials import _crypt, settings_root

MODEL = 'mimo-v2.5-tts'
STYLE = ('年輕成年女性，溫柔親切而有精神，像熟悉的好鄰居自然聊天。'
         '使用地道香港廣東話和香港口音，粵語聲調準確，避免普通話腔、播音腔、誇張撒嬌或卡通童聲。'
         '語速自然稍柔和，停頓短，情緒細膩真誠。只朗讀指定文字，不讀這段指引。')


def synthesize(text, *, client=None):
    if not isinstance(text, str) or not 0 < len(text) <= 1500:
        raise ValueError('invalid_voice_input')
    key = _crypt((settings_root()/'mimo-voice-trial-key.dpapi').read_bytes(), decrypt=True).decode()
    owned = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=False)
    try:
        response = client.post('https://api.xiaomimimo.com/v1/chat/completions', headers={'api-key': key},
            json={'model': MODEL, 'messages': [{'role': 'user', 'content': STYLE},
                {'role': 'assistant', 'content': '(粤语 温柔 甜美)'+text}],
                'audio': {'format': 'wav', 'voice': '冰糖'}}, timeout=20)
        response.raise_for_status()
        if len(response.content) > 30_000_000:
            raise ValueError('voice_response_too_large')
        try:
            data = base64.b64decode(response.json()['choices'][0]['message']['audio']['data'], validate=True)
            with wave.open(io.BytesIO(data), 'rb') as wav:
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or not 8000 <= wav.getframerate() <= 48000 or not 0 < wav.getnframes()/wav.getframerate() <= 120:
                    raise ValueError('invalid_generated_audio')
        except (KeyError, IndexError, TypeError, wave.Error, EOFError) as error:
            raise ValueError('invalid_generated_audio') from error
        return data
    finally:
        if owned:
            client.close()
