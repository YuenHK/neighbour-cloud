"""HTTP creation bounds; historical Event rows retain their existing read model."""
import json
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from edge_hub.events import Event


class IngestEvent(Event):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=128)
    zone: str = Field(min_length=1, max_length=128)
    at_ms: int = Field(strict=True, ge=0, le=2**53 - 1)
    evidence: str | None = Field(default=None, max_length=512)
    status: Literal['pending'] = 'pending'

    @field_validator('id', 'zone', 'evidence')
    @classmethod
    def utf8_text(cls, value):
        if value is not None:
            try:
                value.encode('utf-8')
            except UnicodeEncodeError as error:
                raise ValueError('event text must be valid UTF-8') from error
        return value

    @field_validator('details')
    @classmethod
    def bounded_json_details(cls, value):
        try:
            serialized = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            if len(serialized) > 16384 or len(serialized.encode('utf-8')) > 16384:
                raise ValueError('event details exceed 16 KiB of compact UTF-8 JSON')
        except (TypeError, RecursionError) as error:
            raise ValueError('event details must be finite serializable JSON') from error
        return value
