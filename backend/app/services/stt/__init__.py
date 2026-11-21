"""Canonical STT service package exports."""

from .service import OpenAICompatibleSTTService as OpenAICompatibleSTTService
from .service import STTProviderAttempt as STTProviderAttempt
from .service import STTService as STTService
from .service import STTServiceResolution as STTServiceResolution
from .service import _is_hallucination as is_whisper_hallucination
from .service import get_stt_service as get_stt_service
from .service import resolve_stt_service as resolve_stt_service

__all__ = [
    "OpenAICompatibleSTTService",
    "STTProviderAttempt",
    "STTServiceResolution",
    "STTService",
    "get_stt_service",
    "is_whisper_hallucination",
    "resolve_stt_service",
    "AWSTranscribeSTTService",
    "AzureSpeechSTTService",
]


def __getattr__(name: str):
    """Lazy imports for cloud providers (avoid import errors if boto3/etc not installed)."""
    if name == "AWSTranscribeSTTService":
        from .aws_transcribe import AWSTranscribeSTTService
        return AWSTranscribeSTTService
    if name == "AzureSpeechSTTService":
        from .azure_speech import AzureSpeechSTTService
        return AzureSpeechSTTService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
