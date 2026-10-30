"""Small Cantonese speech cleanup; displayed text and conversation remain intact."""
import json
import os
import re
from pathlib import Path

PRESETS = {
    'original': {'name': 'original', 'pace': 1.0, 'noise': .667, 'duration_noise': .8},
    'conversational': {'name': 'conversational', 'pace': 1.04, 'noise': .55, 'duration_noise': .65},
    'clear': {'name': 'clear', 'pace': 1.08, 'noise': .45, 'duration_noise': .55},
}


def voice_profile():
    filename = os.environ.get('ZHIWEI_VOICE_PROFILE', '')
    try:
        saved = json.loads(Path(filename).read_text(encoding='utf-8')) if filename else {}
        selected = saved.get('preset', 'original')
        return {**PRESETS.get(selected, PRESETS['original']),
                'stt_provider': 'local' if saved.get('stt_provider') == 'local' else 'configured',
                'tts_provider': saved.get('tts_provider') if saved.get('tts_provider') in ('gemini', 'mimo', 'azure') else 'local',
                'gemini_voice': saved.get('gemini_voice') if saved.get('gemini_voice') in ('Leda', 'Zephyr', 'HKSoft') else 'Leda'}
    except (OSError, ValueError, KeyError, TypeError):
        return PRESETS['original']


def spoken_cantonese(text):
    text = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', text)
    text = re.sub(r'https?://\S+', '網頁連結', text)
    for pattern, replacement in [(r'QR\s*Code', '二維碼'), (r'Wi[ -]?Fi', '無線網絡'),
        ('AIRI', '屋苑服務台'), ('EP', '機械人'), ('APP', '應用程式'), ('OK', '好')]:
        # Unicode word boundaries also treat Chinese as word characters.
        text = re.sub(r'(?<![A-Za-z])'+pattern+r'(?![A-Za-z])', replacement, text, flags=re.IGNORECASE)
    text = re.sub(r'HK\$\s*(\d+(?:\.\d+)?)', r'\1港元', text)
    text = re.sub(r'(?m)^\s*(?:#{1,6}|[-*])\s+', '', text)
    return text.replace('**', '').replace('`', '')
