from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TTSConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    default_voice: str | None = None
    default_speed: float | None = Field(default=None, ge=0.25, le=4.0)
    allow_provider_fallback: bool | None = None


class TTSProviderUpsertRequest(BaseModel):
    provider: str = Field(min_length=1)
    enabled: bool = True
    priority: int = 0
    config: dict[str, Any] = Field(default_factory=dict)


class TTSSynthesizeRequest(BaseModel):
    text: str = Field(min_length=1)
    provider: str | None = None
    voice: str | None = None
    speed: float | None = Field(default=None, ge=0.25, le=4.0)


class TTSMaskedConfigUpdateRequest(BaseModel):
    openai_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    aws_polly_access_key_id: str | None = None
    aws_polly_secret_key: str | None = None
    stt_openai_api_key: str | None = None


__all__ = [
    "TTSConfigUpdateRequest",
    "TTSMaskedConfigUpdateRequest",
    "TTSProviderUpsertRequest",
    "TTSSynthesizeRequest",
]
