"""Pydantic schemas for the admin panel STT provider configuration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class STTLocalWhisperConfig(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    endpoint_path: str | None = None


class STTAWSTranscribeConfig(BaseModel):
    access_key_id: str | None = None
    secret_access_key: str | None = None
    region: str | None = None
    language_code: str | None = None
    enable_diarization: bool | None = None


class STTAzureSpeechConfig(BaseModel):
    subscription_key: str | None = None
    region: str | None = None
    language: str | None = None
    enable_diarization: bool | None = None


class STTOpenAIWhisperConfig(BaseModel):
    api_key: str | None = None


class STTConfigUpdateRequest(BaseModel):
    """Full STT configuration payload for save/update."""
    active_provider: str | None = None
    language: str | None = None
    providers: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "STTAWSTranscribeConfig",
    "STTAzureSpeechConfig",
    "STTConfigUpdateRequest",
    "STTLocalWhisperConfig",
    "STTOpenAIWhisperConfig",
]
