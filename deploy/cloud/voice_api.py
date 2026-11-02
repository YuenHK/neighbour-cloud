"""Authenticated-cloud HiuMaan PCM routing without loading local audio app."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from deploy.cloud.airi_runtime import StrictSettings
from edge_hub import azure_voice
from edge_hub.event_request import EventBodyLimitMiddleware
from local_audio_gateway.resident_stream import stream_router
from local_audio_gateway.voice_style import spoken_cantonese

STREAM_PATH = '/v1/audio/resident-stream'
STREAM_PATHS = frozenset((STREAM_PATH, '/_audio' + STREAM_PATH))


class SpeechStyle(StrictSettings):
    rate: float = Field(default=1., ge=.5, le=2)
    pitch: float = Field(default=0., ge=-30, le=30)
    volume: float = Field(default=0., ge=-30, le=30)


class CloudSpeech(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    model: str = Field(default=azure_voice.MODEL, max_length=100)
    voice: str = Field(default=azure_voice.VOICE, max_length=100)
    input: str = Field(min_length=1, max_length=1500)
    speed: float = Field(default=1.0, ge=.5, le=2)
    response_format: Literal['wav'] = 'wav'  # Compatibility field; endpoint protocol is PCM SSE.
    preview: SpeechStyle | None = None  # Staff manual preview only, never a resident override.

    @field_validator('input')
    @classmethod
    def valid_text(cls, text):
        if '\x00' in text or any(0xD800 <= ord(char) <= 0xDFFF for char in text):
            raise ValueError('invalid_voice_text')
        return text


class CloudVoiceBodyLimit(EventBodyLimitMiddleware):
    label = 'resident voice'

    def __init__(self, app):
        super().__init__(app, max_bytes=8192, timeout_seconds=5, max_depth=16)

    def matches(self, scope):
        return (scope['type'] == 'http' and scope.get('method') == 'POST'
                and scope.get('path') in STREAM_PATHS)


def voice_router(chunks_factory, *, runtime=None, options_chunks_factory=None, staff_preview=None):
    def options(body):
        if body.preview is not None:
            if staff_preview is None or not staff_preview():
                raise HTTPException(403, '試聽設定只供管理工作台使用。')
            return body.preview.model_dump()
        if runtime is None:
            return None
        value = runtime()['speech']
        return {key: value[key] for key in ('rate', 'pitch', 'volume')}
    shared = stream_router(CloudSpeech, lambda: {'tts_provider': 'azure'}, spoken_cantonese,
                           chunks_factory=chunks_factory, render_options=options,
                           options_chunks_factory=options_chunks_factory or (
                               lambda text, _options: (chunks_factory or azure_voice.pcm_chunks)(text)))
    router = APIRouter()
    router.include_router(shared)
    router.include_router(shared, prefix='/_audio')  # Same cache/dedup/slots, not a second engine.
    return router
