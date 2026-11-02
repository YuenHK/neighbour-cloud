"""Published native AIRI module preferences; no credentials or arbitrary endpoints."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Consciousness(StrictSettings):
    provider: Literal['cloudflare-workers-ai'] = 'cloudflare-workers-ai'
    model: Literal['gemma-4-26b-a4b-it'] = 'gemma-4-26b-a4b-it'


class Speech(StrictSettings):
    provider: Literal['microsoft-speech'] = 'microsoft-speech'
    model: Literal['azure-hiumaan-f0'] = 'azure-hiumaan-f0'
    voice_id: Literal['zh-HK-HiuMaanNeural'] = 'zh-HK-HiuMaanNeural'
    rate: float = Field(default=1.0, ge=.5, le=2)
    pitch: float = Field(default=0.0, ge=-30, le=30)
    volume: float = Field(default=0.0, ge=-30, le=30)


class Hearing(StrictSettings):
    provider: Literal['openai-compatible-audio-transcription'] = 'openai-compatible-audio-transcription'
    model: Literal['@cf/openai/whisper-large-v3-turbo'] = '@cf/openai/whisper-large-v3-turbo'
    microphone_enabled: bool = True
    auto_send: bool = True


class WebSearch(StrictSettings):
    enabled: bool = True


class Memory(StrictSettings):
    long_term_enabled: bool = True
    # Shared resident screens never retain a session beyond the existing limit.
    idle_seconds: int = Field(default=180, ge=60, le=180)
    context_messages: int = Field(default=60, ge=4, le=60)
    context_characters: int = Field(default=16000, ge=2000, le=16000)


class AiriRuntime(StrictSettings):
    consciousness: Consciousness = Field(default_factory=Consciousness)
    speech: Speech = Field(default_factory=Speech)
    hearing: Hearing = Field(default_factory=Hearing)
    web_search: WebSearch = Field(default_factory=WebSearch)
    memory: Memory = Field(default_factory=Memory)


def catalog():
    """Inspect owned configuration only. Never list/ping a supplier over network."""
    import json

    from edge_hub import azure_voice, cloudflare_gemma
    from edge_hub.estate_services import search_key
    from edge_hub.storage_context import current_storage

    whisper = False
    storage = current_storage()
    if storage is not None:
        try:
            approved = json.loads((storage.settings_root / 'cloudflare-whisper-free.json').read_text(encoding='utf-8'))
            whisper = approved == {'enabled': True, 'user_approved': True,
                                    'model': Hearing().model, 'plan': 'Free'}
        except (OSError, ValueError, TypeError):
            pass
    gemma = bool(cloudflare_gemma.configuration())

    return {'free_only': True, 'credentials_managed': True,
            'configured': {'cloudflare-workers-ai': gemma,
                           'microsoft-speech': azure_voice.configured(),
                           'openai-compatible-audio-transcription': gemma and whisper,
                           'tavily': bool(search_key())},
            'runtime_defaults': AiriRuntime().model_dump()}
