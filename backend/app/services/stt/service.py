"""Speech-to-Text provider resolution for server-side transcription."""

from __future__ import annotations

import logging
import mimetypes
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.services.error_facts import error_text

logger = logging.getLogger(__name__)

# --- Whisper hallucination filter ---
# Whisper models (especially smaller ones like base/small) hallucinate these
# patterns when the input audio is silence, background noise, or hold music.
# They should be treated as empty transcriptions.
_HALLUCINATION_PATTERNS: list[re.Pattern] = [
    # German hallucinations
    re.compile(r"^\s*\*?\s*Musik\s*\*?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[\s*Musik\s*\]\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(\s*Musik\s*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\*?\s*Klingel\s*\*?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[\s*Klingel\s*\]\s*$", re.IGNORECASE),
    re.compile(r"^\s*\*?\s*Stille\s*\*?\s*$", re.IGNORECASE),
    # English hallucinations
    re.compile(r"^\s*\*?\s*Music\s*\*?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[\s*Music\s*\]\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(\s*Music\s*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\*?\s*Silence\s*\*?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[\s*Silence\s*\]\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(\s*Silence\s*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\*?\s*Applause\s*\*?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[\s*Applause\s*\]\s*$", re.IGNORECASE),
    re.compile(r"^\s*\*?\s*Laughter\s*\*?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[\s*Laughter\s*\]\s*$", re.IGNORECASE),
    # BLANK_AUDIO and other bracket-wrapped single-word indicators
    re.compile(r"^\s*\[\s*BLANK_AUDIO\s*\]\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[\s*blank\s*\]\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[\s*inaudible\s*\]\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[\s*no\s*speech\s*\]\s*$", re.IGNORECASE),
    # Generic whisper hallucination: repeated punctuation-only or very short non-word
    re.compile(r"^\s*[\.\,\!\?\-\*\[\]\(\)]+\s*$"),
    # "Thank you." repeated (common hallucination on silence)
    re.compile(r"^\s*(Thank you\.?\s*)+$", re.IGNORECASE),
    # Whisper's known German outputs on silence (thanks; subtitle credits): artifacts of the model's training data,
    # filtered like their English twins; this is not a language branch, the transcript language is untouched.
    re.compile(r"^\s*(Danke\.?\s*)+$", re.IGNORECASE),
    re.compile(r"^\s*Untertitel.*$", re.IGNORECASE),
    re.compile(r"^\s*Subtitles?\s*(by|im)?\s*.*$", re.IGNORECASE),
    # Single repeated character hallucination
    re.compile(r"^\s*(.)\1{4,}\s*$"),
    # Very short single word that's likely not meaningful speech (1-2 chars)
    re.compile(r"^\s*\w{1,2}[\.\,]?\s*$"),
]

# Threshold for no_speech_prob — if above this, treat as no speech detected.
# Set high (0.9) because whisper often assigns 0.7-0.85 to real speech with
# background noise. Only filter segments that are almost certainly silence.
_NO_SPEECH_PROB_THRESHOLD = 0.9

# If transcribed text has more characters than this, keep it regardless of
# no_speech_prob (clearly real content, not a hallucination).
_MIN_CHARS_OVERRIDE_NSPROB = 15
_TRANSCRIPTION = "stt.transcription"


async def _stt_setting(db, field_name: str):
    from ..secret import get_secret_value

    return await get_secret_value(db, tool_name="stt", field_name=field_name, project_id=None, purpose=_TRANSCRIPTION)


def _is_hallucination(text: str) -> bool:
    """Return True if the transcription text matches a known hallucination pattern."""
    if not text or not text.strip():
        return True
    stripped = text.strip()
    for pattern in _HALLUCINATION_PATTERNS:
        if pattern.match(stripped):
            return True
    return False


def _audio_content_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _build_endpoint_url(base_url: str, endpoint_path: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("STT base URL must be an absolute http(s) URL")
    return urljoin(base_url.rstrip("/") + "/", endpoint_path.lstrip("/"))


def _extract_transcript_text(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        text = response.text.strip()
        logger.debug("STT: received non-json transcription response")
        return "" if _is_hallucination(text) else text

    payload = response.json()
    payload_keys = list(payload.keys()) if isinstance(payload, dict) else type(payload)
    logger.debug("STT: received json transcription response with keys=%s", payload_keys)
    if isinstance(payload, dict):
        # verbose_json format includes segments with no_speech_prob
        segments = payload.get("segments")
        if isinstance(segments, list) and segments:
            # Filter out segments with high no_speech_prob
            valid_texts = []
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                no_speech_prob = segment.get("no_speech_prob", 0.0)
                seg_text = (segment.get("text") or "").strip()
                logger.debug("STT: evaluating segment no_speech_prob=%.4f", no_speech_prob)
                if no_speech_prob >= _NO_SPEECH_PROB_THRESHOLD and len(seg_text) < _MIN_CHARS_OVERRIDE_NSPROB:
                    logger.debug(
                        "STT: dropping segment with no_speech_prob=%.3f",
                        no_speech_prob,
                    )
                    continue
                if seg_text and not _is_hallucination(seg_text):
                    valid_texts.append(seg_text)
                else:
                    logger.debug("STT: filtered hallucination-like segment")
            result = " ".join(valid_texts).strip()
            logger.debug("STT: extracted transcript from %d valid segment(s)", len(valid_texts))
            return "" if _is_hallucination(result) else result

        # Simple json format: just has "text"
        for key in ("text", "transcript", "transcription"):
            value = payload.get(key)
            if isinstance(value, str):
                text = value.strip()
                if _is_hallucination(text):
                    logger.debug("STT: filtered hallucination-like simple response")
                    return ""
                logger.debug("STT: extracted transcript from simple response key=%s", key)
                return text
    logger.debug("STT: returning empty transcript because no supported response field matched")
    return ""


class STTService:
    """Transcribe audio bytes using OpenAI Whisper API."""

    def __init__(self, api_key: str, model: str = "whisper-1", language: str | None = None):
        self.api_key = api_key
        self.model = model
        self.language = language  # ISO-639-1 code, e.g. "en", "de" - None = auto-detect
        self.provider_name = "openai_whisper"

    async def transcribe(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        """Send audio bytes to Whisper API and return transcription text."""
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        files = {"file": (filename, audio_bytes, _audio_content_type(filename))}
        data = {"model": self.model}
        if self.language:
            data["language"] = self.language
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
            resp.raise_for_status()
            return _extract_transcript_text(resp)


class OpenAICompatibleSTTService:
    """Transcribe audio through an OpenAI-compatible HTTP gateway."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        model: str = "unmute",
        endpoint_path: str = "/v1/audio/transcriptions",
        language: str | None = None,
        provider_name: str = "openai_compatible",
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.endpoint_path = endpoint_path
        self.language = language
        self.provider_name = provider_name

    async def transcribe(self, audio_bytes: bytes, filename: str = "audio.wav") -> str:
        url = _build_endpoint_url(self.base_url, self.endpoint_path)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        files = {"file": (filename, audio_bytes, _audio_content_type(filename))}
        # Use verbose_json to get per-segment no_speech_prob for hallucination filtering
        data = {"model": self.model, "response_format": "verbose_json"}
        if self.language:
            data["language"] = self.language
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
            resp.raise_for_status()
            return _extract_transcript_text(resp)


@dataclass(frozen=True)
class STTProviderAttempt:
    provider: str
    status: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class STTServiceResolution:
    service: Any | None
    selected_provider: str | None
    fallback_allowed: bool
    fallback_used: bool = False
    attempts: list[STTProviderAttempt] = field(default_factory=list)

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "selected_provider": self.selected_provider,
            "fallback_allowed": self.fallback_allowed,
            "fallback_used": self.fallback_used,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }


def _truthy_config(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value or "").strip().lower()
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    return default


def _selected_resolution(
    service: Any,
    *,
    provider: str,
    fallback_allowed: bool,
    attempts: list[STTProviderAttempt],
) -> STTServiceResolution:
    attempts.append(STTProviderAttempt(provider, "selected", "provider_selected"))
    fallback_used = any(attempt.status == "failed" for attempt in attempts[:-1])
    return STTServiceResolution(
        service=service,
        selected_provider=provider,
        fallback_allowed=fallback_allowed,
        fallback_used=fallback_used,
        attempts=attempts,
    )


def _blocked_resolution(
    *,
    fallback_allowed: bool,
    attempts: list[STTProviderAttempt],
) -> STTServiceResolution:
    attempts.append(STTProviderAttempt("fallback_policy", "blocked", "fallback_disabled_after_configured_failure"))
    return STTServiceResolution(
        service=None,
        selected_provider=None,
        fallback_allowed=fallback_allowed,
        fallback_used=False,
        attempts=attempts,
    )


async def resolve_stt_service(db, project_id: str | None = None) -> STTServiceResolution:
    """Return the configured STT provider, preferring local/self-hosted endpoints."""
    attempts: list[STTProviderAttempt] = []
    fallback_allowed = True
    try:
        from ..secret import get_secret_value

        fallback_allowed = _truthy_config(
            await _stt_setting(db, "allow_provider_fallback"),
            default=True,
        )
        whisper_base_url = await _stt_setting(db, "whisper_base_url")
        if whisper_base_url:
            try:
                whisper_api_key = await _stt_setting(db, "whisper_api_key")
                whisper_model = await _stt_setting(db, "whisper_model")
                whisper_endpoint_path = await _stt_setting(db, "whisper_endpoint_path")
                language = await _stt_setting(db, "language")
                service = OpenAICompatibleSTTService(
                    base_url=whisper_base_url,
                    api_key=whisper_api_key,
                    model=whisper_model or "base",
                    endpoint_path=whisper_endpoint_path or "/v1/audio/transcriptions",
                    language=language,
                    provider_name="local_whisper",
                )
                _build_endpoint_url(service.base_url, service.endpoint_path)
                return _selected_resolution(
                    service,
                    provider="local_whisper",
                    fallback_allowed=fallback_allowed,
                    attempts=attempts,
                )
            except ValueError as e:
                logger.warning("Local Whisper STT configuration is invalid: %s", error_text("stt_config_invalid", e))
                attempts.append(STTProviderAttempt("local_whisper", "failed", "invalid_configuration"))
                if not fallback_allowed:
                    return _blocked_resolution(fallback_allowed=fallback_allowed, attempts=attempts)
        else:
            attempts.append(STTProviderAttempt("local_whisper", "skipped", "not_configured"))

        # --- AWS Transcribe (cloud with diarization) ---
        aws_access_key = await _stt_setting(db, "aws_access_key_id")
        aws_secret_key = await _stt_setting(db, "aws_secret_access_key")
        if aws_access_key and aws_secret_key:
            try:
                from .aws_transcribe import AWSTranscribeSTTService

                aws_region = await _stt_setting(db, "aws_region")
                aws_language = await _stt_setting(db, "aws_language_code")
                language = await _stt_setting(db, "language")
                aws_diarization = await _stt_setting(db, "aws_enable_diarization")

                service = AWSTranscribeSTTService(
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_key,
                    aws_region=aws_region or "eu-central-1",
                    language_code=aws_language or language or "en-US",
                    enable_diarization=aws_diarization != "false",
                )
                return _selected_resolution(
                    service,
                    provider="aws_transcribe",
                    fallback_allowed=fallback_allowed,
                    attempts=attempts,
                )
            except ImportError:
                logger.warning("AWS Transcribe configured but boto3 not installed")
                attempts.append(STTProviderAttempt("aws_transcribe", "failed", "dependency_missing"))
                if not fallback_allowed:
                    return _blocked_resolution(fallback_allowed=fallback_allowed, attempts=attempts)
            except Exception as e:
                logger.warning("AWS Transcribe configuration is invalid: %s", error_text("stt_config_invalid", e))
                attempts.append(STTProviderAttempt("aws_transcribe", "failed", "invalid_configuration"))
                if not fallback_allowed:
                    return _blocked_resolution(fallback_allowed=fallback_allowed, attempts=attempts)
        else:
            attempts.append(STTProviderAttempt("aws_transcribe", "skipped", "missing_credentials"))

        # --- Azure Speech (cloud with diarization) ---
        azure_key = await _stt_setting(db, "azure_subscription_key")
        if azure_key:
            try:
                from .azure_speech import AzureSpeechSTTService

                azure_region = await _stt_setting(db, "azure_region")
                azure_language = await _stt_setting(db, "azure_language")
                language = await _stt_setting(db, "language")
                azure_diarization = await _stt_setting(db, "azure_enable_diarization")

                service = AzureSpeechSTTService(
                    subscription_key=azure_key,
                    region=azure_region or "westeurope",
                    language=azure_language or language or "en-US",
                    enable_diarization=azure_diarization != "false",
                )
                return _selected_resolution(
                    service,
                    provider="azure_speech",
                    fallback_allowed=fallback_allowed,
                    attempts=attempts,
                )
            except ImportError:
                logger.warning("Azure Speech configured but httpx not available")
                attempts.append(STTProviderAttempt("azure_speech", "failed", "dependency_missing"))
                if not fallback_allowed:
                    return _blocked_resolution(fallback_allowed=fallback_allowed, attempts=attempts)
            except Exception as e:
                logger.warning("Azure Speech configuration is invalid: %s", error_text("stt_config_invalid", e))
                attempts.append(STTProviderAttempt("azure_speech", "failed", "invalid_configuration"))
                if not fallback_allowed:
                    return _blocked_resolution(fallback_allowed=fallback_allowed, attempts=attempts)
        else:
            attempts.append(STTProviderAttempt("azure_speech", "skipped", "not_configured"))

        # --- OpenAI Whisper Cloud (fallback) ---
        key = await _stt_setting(db, "openai_api_key")
        key_source = "stt.openai_api_key"
        if not key and fallback_allowed:
            # Fallback: try tts key (same OpenAI account)
            key = await get_secret_value(db, tool_name="tts", field_name="openai_api_key", project_id=None,
                                         purpose=_TRANSCRIPTION)
            key_source = "tts.openai_api_key"
        if key:
            attempts.append(STTProviderAttempt("openai_whisper", "configured", key_source))
            return _selected_resolution(
                STTService(api_key=key),
                provider="openai_whisper",
                fallback_allowed=fallback_allowed,
                attempts=attempts,
            )
        attempts.append(STTProviderAttempt("openai_whisper", "skipped", "missing_credentials"))
    except Exception as e:
        logger.warning("Could not load STT service: %s", error_text("stt_service_load_failed", e))
        attempts.append(STTProviderAttempt("stt_resolution", "failed", "unexpected_error"))
    return STTServiceResolution(
        service=None,
        selected_provider=None,
        fallback_allowed=fallback_allowed,
        fallback_used=False,
        attempts=attempts,
    )


async def get_stt_service(db, project_id: str | None = None):
    resolution = await resolve_stt_service(db, project_id=project_id)
    return resolution.service
