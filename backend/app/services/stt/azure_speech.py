"""Azure Speech Service STT with built-in Speaker Diarization.

Uses Azure Cognitive Services Speech SDK (REST API variant) for
speech-to-text with optional speaker diarization.

References:
    https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-to-text
    https://learn.microsoft.com/en-us/azure/ai-services/speech-service/get-started-stt-diarization
    https://learn.microsoft.com/en-us/rest/api/speechtotext/transcriptions
"""

from __future__ import annotations

import io
import json
import logging
import wave
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AzureSpeechSegment:
    """A transcribed segment with optional speaker info."""

    text: str
    speaker_id: str | None = None
    offset_ms: int = 0
    duration_ms: int = 0
    confidence: float = 1.0


@dataclass
class AzureSpeechResult:
    """Result from Azure Speech with diarization info."""

    text: str
    segments: list[AzureSpeechSegment] = field(default_factory=list)
    num_speakers: int = 0
    language_detected: str | None = None


class AzureSpeechSTTService:
    """Transcribe audio using Azure Cognitive Services Speech-to-Text.

    Supports two modes:
    1. Simple recognition (short audio <60s) via REST API
    2. Batch transcription (longer audio) via Batch Transcription API

    Both support speaker diarization when enabled.
    """

    def __init__(
        self,
        *,
        subscription_key: str,
        region: str = "westeurope",
        language: str = "en-US",
        enable_diarization: bool = True,
        max_speakers: int = 5,
        endpoint: str | None = None,
    ):
        self.subscription_key = subscription_key
        self.region = region
        self.language = language
        self.enable_diarization = enable_diarization
        self.max_speakers = max_speakers
        self.endpoint = endpoint or f"https://{region}.stt.speech.microsoft.com"
        self.provider_name = "azure_speech"

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        *,
        diarization: bool | None = None,
    ) -> str:
        """Transcribe audio bytes. Returns plain text."""
        result = await self.transcribe_with_diarization(
            audio_bytes, filename=filename, diarization=diarization
        )
        return result.text

    async def transcribe_with_diarization(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        *,
        diarization: bool | None = None,
    ) -> AzureSpeechResult:
        """Transcribe with full diarization result.

        For short audio (<60s), uses the real-time REST API with conversation transcription.
        For longer audio, uses the Batch Transcription API.
        """
        use_diarization = diarization if diarization is not None else self.enable_diarization
        duration_sec = self._estimate_duration(audio_bytes)

        if duration_sec < 60 and not use_diarization:
            # Simple recognition for short audio without diarization
            return await self._simple_recognize(audio_bytes)
        else:
            # Batch transcription for diarization or longer audio
            return await self._batch_transcribe(audio_bytes, use_diarization)

    async def _simple_recognize(self, audio_bytes: bytes) -> AzureSpeechResult:
        """Use the simple REST recognition endpoint (no diarization)."""
        url = (
            f"https://{self.region}.stt.speech.microsoft.com"
            f"/speech/recognition/conversation/cognitiveservices/v1"
            f"?language={self.language}&format=detailed"
        )

        headers = {
            "Ocp-Apim-Subscription-Key": self.subscription_key,
            "Content-Type": self._content_type(audio_bytes),
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, content=audio_bytes)
            resp.raise_for_status()
            data = resp.json()

        # Parse simple recognition result
        recognition_status = data.get("RecognitionStatus", "")
        if recognition_status != "Success":
            logger.debug("Azure STT recognition status: %s", recognition_status)
            return AzureSpeechResult(text="")

        # Get best result from NBest
        nbest = data.get("NBest", [])
        if nbest:
            best = max(nbest, key=lambda x: x.get("Confidence", 0))
            text = best.get("Display", best.get("Lexical", "")).strip()
        else:
            text = data.get("DisplayText", "").strip()

        from .service import _is_hallucination

        if _is_hallucination(text):
            return AzureSpeechResult(text="")

        return AzureSpeechResult(
            text=text,
            segments=[AzureSpeechSegment(text=text)] if text else [],
        )

    async def _batch_transcribe(
        self, audio_bytes: bytes, use_diarization: bool
    ) -> AzureSpeechResult:
        """Use the Batch Transcription API (supports diarization).

        Flow:
        1. Create transcription job with inline audio content (base64)
        2. Poll for completion
        3. Fetch results with speaker labels
        """

        # For the batch API, we need to provide audio via a URL.
        # Since we have bytes, we'll use the real-time conversation transcription
        # via the Speech SDK REST approach instead.
        # Alternative: Use the fast transcription endpoint (preview)
        return await self._fast_transcription(audio_bytes, use_diarization)

    async def _fast_transcription(
        self, audio_bytes: bytes, use_diarization: bool
    ) -> AzureSpeechResult:
        """Use the Azure Fast Transcription API (supports diarization, no S3 needed).

        This is the recommended approach for files < 2 hours.
        Endpoint: POST /speechtotext/transcriptions:transcribe?api-version=2024-11-15
        """
        url = (
            f"https://{self.region}.api.cognitive.microsoft.com"
            f"/speechtotext/transcriptions:transcribe?api-version=2024-11-15"
        )

        headers = {
            "Ocp-Apim-Subscription-Key": self.subscription_key,
            "Accept": "application/json",
        }

        # Build the definition JSON
        definition: dict[str, Any] = {
            "locales": [self.language],
            "profanityFilterMode": "None",
        }

        if use_diarization:
            definition["diarizationSettings"] = {
                "minSpeakers": 1,
                "maxSpeakers": self.max_speakers,
            }

        # Multipart form: definition (JSON) + audio file

        # Use httpx multipart
        async with httpx.AsyncClient(timeout=120) as client:
            files = {
                "audio": (
                    "audio.wav",
                    audio_bytes,
                    self._content_type(audio_bytes),
                ),
            }
            data = {
                "definition": json.dumps(definition),
            }

            resp = await client.post(url, headers=headers, files=files, data=data)

            if resp.status_code == 200:
                result_data = resp.json()
                return self._parse_fast_transcription_result(result_data, use_diarization)
            elif resp.status_code == 401:
                raise RuntimeError(
                    f"Azure Speech: Authentication failed. Check subscription key and region. "
                    f"Status: {resp.status_code}"
                )
            else:
                logger.error(
                    "Azure Fast Transcription failed: HTTP %d body_chars=%d", resp.status_code, len(resp.text or "")
                )
                # Fallback to simple recognition
                if not use_diarization:
                    return await self._simple_recognize(audio_bytes)
                raise RuntimeError(f"azure_fast_transcription_failed http_status={resp.status_code}")

    def _parse_fast_transcription_result(
        self, data: dict, use_diarization: bool
    ) -> AzureSpeechResult:
        """Parse Azure Fast Transcription response."""
        combined_phrases = data.get("combinedPhrases", [])
        phrases = data.get("phrases", [])

        # Get full text from combinedPhrases
        full_text = ""
        if combined_phrases:
            full_text = " ".join(
                cp.get("text", "") for cp in combined_phrases
            ).strip()

        segments: list[AzureSpeechSegment] = []
        speaker_ids: set[str] = set()

        for phrase in phrases:
            text = phrase.get("text", "").strip()
            if not text:
                continue

            speaker = phrase.get("speaker")
            offset = phrase.get("offsetMilliseconds", 0)
            duration = phrase.get("durationMilliseconds", 0)
            confidence = phrase.get("confidence", 1.0)

            speaker_id = str(speaker) if speaker is not None else None
            if speaker_id:
                speaker_ids.add(speaker_id)

            segments.append(
                AzureSpeechSegment(
                    text=text,
                    speaker_id=speaker_id,
                    offset_ms=offset,
                    duration_ms=duration,
                    confidence=confidence,
                )
            )

        from .service import _is_hallucination

        if _is_hallucination(full_text):
            full_text = ""
            segments = []

        detected_lang = data.get("language")

        return AzureSpeechResult(
            text=full_text,
            segments=segments,
            num_speakers=len(speaker_ids),
            language_detected=detected_lang,
        )

    @staticmethod
    def _content_type(audio_bytes: bytes) -> str:
        """Detect content type from audio bytes."""
        if audio_bytes[:4] == b"RIFF":
            return "audio/wav"
        if audio_bytes[:3] == b"ID3" or audio_bytes[:2] == b"\xff\xfb":
            return "audio/mpeg"
        if audio_bytes[:4] == b"OggS":
            return "audio/ogg"
        if audio_bytes[:4] == b"fLaC":
            return "audio/flac"
        return "audio/wav"

    @staticmethod
    def _estimate_duration(audio_bytes: bytes) -> float:
        """Estimate audio duration in seconds from WAV header."""
        if audio_bytes[:4] == b"RIFF" and len(audio_bytes) > 44:
            try:
                buf = io.BytesIO(audio_bytes)
                with wave.open(buf, "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    if rate > 0:
                        return frames / rate
            except Exception:
                pass
        # Rough estimate: assume 16kHz 16-bit mono WAV
        return len(audio_bytes) / 32000
