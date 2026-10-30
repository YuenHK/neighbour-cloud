"""Text-only bounded client history. Never carries tools, images or role overrides."""
from fastapi import HTTPException

MAX_MESSAGES = 12
MAX_CHARACTERS = 8000
MAX_MESSAGE_CHARACTERS = 4000


def text_content(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return ' '.join(part['text'] for part in content
                        if isinstance(part, dict) and part.get('type') == 'text'
                        and isinstance(part.get('text'), str)).strip()
    return ''


def bounded_history(payload, *, max_messages=MAX_MESSAGES, max_characters=MAX_CHARACTERS):
    messages = payload.get('messages', [])
    if not isinstance(messages, list) or len(messages) > 256:
        raise HTTPException(400, 'invalid conversation messages')
    retained = []
    remaining = max_characters
    for message in reversed(messages):
        if not isinstance(message, dict):
            raise HTTPException(400, 'invalid conversation message')
        if message.get('role') not in ('user', 'assistant') or message.get('tool_calls'):
            continue
        text = text_content(message.get('content'))
        if not text:
            continue
        if len(text) > MAX_MESSAGE_CHARACTERS or len(text) > remaining:
            if not retained:
                raise HTTPException(400, 'current conversation text exceeds limit')
            break
        if any(0xD800 <= ord(char) <= 0xDFFF for char in text):
            raise HTTPException(400, 'invalid conversation text')
        retained.append({'role': message['role'], 'content': text})
        remaining -= len(text)
        if len(retained) == max_messages:
            break
    retained.reverse()
    # Never start with an orphaned answer after evicting an earlier question.
    while retained and retained[0]['role'] != 'user':
        retained.pop(0)
    return retained


def resident_history(payload):
    """One kiosk session, shared unchanged between free cloud candidates."""
    return bounded_history(payload, max_messages=60, max_characters=16000)


def response_style(payload):
    return 'voice' if payload.get('zhiwei_response_style') == 'voice' else 'text'
