"""AWS Transcribe STT Service with built-in Speaker Diarization.

Uses Amazon Transcribe streaming or batch API for speech-to-text with
optional speaker diarization (up to 10 speakers).

References:
    https://docs.aws.amazon.com/transcribe/latest/dg/diarization.html
    https://docs.aws.amazon.com/transcribe/latest/APIReference/API_streaming_StartStreamTranscription.html
"""

from __future__ import annotations

import io
import json
import logging
import uuid
import wave
from dataclasses import dataclass
from typing import Any

from ..error_facts import error_type

logger = logging.getLogger(__name__)


@dataclass
class TranscribeSegment:
    """A transcribed segment with optional speaker label."""

    text: str
    speaker_label: str | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    confidence: float = 1.0


@dataclass
class TranscribeResult:
    """Result from AWS Transcribe with diarization info."""

    text: str
    segments: list[TranscribeSegment]
    num_speakers: int = 0
    speaker_labels: dict[str, str] = None  # speaker_id -> mapped name (if available)

    def __post_init__(self):
        if self.speaker_labels is None:
            self.speaker_labels = {}


class AWSTranscribeSTTService:
    """Transcribe audio using AWS Transcribe with optional speaker diarization.

    This service uses the AWS Transcribe batch API (via pre-signed S3 URLs or
    direct audio upload to the TranscribeService). For short audio (<60s),
    it uses the synchronous StartTranscriptionJob approach with inline media.

    For real-time streaming, see AWSTranscribeStreamingService (future).
    """

    def __init__(
        self,
        *,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        aws_region: str = "eu-central-1",
        language_code: str = "en-US",
        enable_diarization: bool = True,
        max_speakers: int = 5,
        vocabulary_name: str | None = None,
    ):
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_region = aws_region
        self.language_code = language_code
        self.enable_diarization = enable_diarization
        self.max_speakers = max_speakers
        self.vocabulary_name = vocabulary_name
        self.provider_name = "aws_transcribe"

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        *,
        diarization: bool | None = None,
    ) -> str:
        """Transcribe audio bytes using AWS Transcribe.

        Returns the plain transcription text. For diarization results,
        use transcribe_with_diarization().
        """
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
    ) -> TranscribeResult:
        """Transcribe audio and return full result with speaker diarization.

        Uses AWS Transcribe via boto3 (async wrapper).
        """
        import asyncio

        use_diarization = diarization if diarization is not None else self.enable_diarization

        return await asyncio.get_event_loop().run_in_executor(
            None,
            self._transcribe_sync,
            audio_bytes,
            filename,
            use_diarization,
        )

    def _transcribe_sync(
        self,
        audio_bytes: bytes,
        filename: str,
        use_diarization: bool,
    ) -> TranscribeResult:
        """Synchronous transcription using boto3."""
        import time

        import boto3

        session = boto3.Session(
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.aws_region,
        )

        # Determine media format from filename/bytes
        media_format = self._detect_format(audio_bytes, filename)
        sample_rate = self._detect_sample_rate(audio_bytes, media_format)

        # Upload to S3 (Transcribe requires S3 URI or URL)
        s3 = session.client("s3")
        transcribe_client = session.client("transcribe")

        # Use a temporary bucket or inline approach
        # For simplicity, use the medical/standard Transcribe with direct content
        job_name = f"octryx-stt-{uuid.uuid4().hex[:12]}"

        # Check if we have a bucket configured, otherwise use inline
        bucket_name = f"octryx-transcribe-{self.aws_region}-temp"

        try:
            s3.head_bucket(Bucket=bucket_name)
        except Exception:
            # Create temp bucket if it doesn't exist
            try:
                if self.aws_region == "us-east-1":
                    s3.create_bucket(Bucket=bucket_name)
                else:
                    s3.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={"LocationConstraint": self.aws_region},
                    )
                # Set lifecycle to auto-delete after 1 day
                s3.put_bucket_lifecycle_configuration(
                    Bucket=bucket_name,
                    LifecycleConfiguration={
                        "Rules": [
                            {
                                "ID": "auto-delete-temp",
                                "Status": "Enabled",
                                "Expiration": {"Days": 1},
                                "Filter": {"Prefix": ""},
                            }
                        ]
                    },
                )
            except Exception as e:
                logger.warning("Could not create temp S3 bucket: error_type=%s", error_type(e))
                raise RuntimeError(
                    f"AWS Transcribe requires an S3 bucket. Could not create '{bucket_name}' "
                    f"(error_type={error_type(e)})"
                ) from e

        # Upload audio to S3
        s3_key = f"audio/{job_name}.{media_format}"
        s3.put_object(Bucket=bucket_name, Key=s3_key, Body=audio_bytes)
        media_uri = f"s3://{bucket_name}/{s3_key}"

        # Build transcription job settings
        settings: dict[str, Any] = {}
        if use_diarization:
            settings["ShowSpeakerLabels"] = True
            settings["MaxSpeakerLabels"] = self.max_speakers
        if self.vocabulary_name:
            settings["VocabularyName"] = self.vocabulary_name

        # Start transcription job
        job_params: dict[str, Any] = {
            "TranscriptionJobName": job_name,
            "Media": {"MediaFileUri": media_uri},
            "MediaFormat": media_format,
            "LanguageCode": self.language_code,
        }
        if sample_rate:
            job_params["MediaSampleRateHertz"] = sample_rate
        if settings:
            job_params["Settings"] = settings

        transcribe_client.start_transcription_job(**job_params)

        # Poll for completion (usually 5-15s for short audio)
        max_wait = 60
        poll_interval = 2
        elapsed = 0

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            status = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
            job_status = status["TranscriptionJob"]["TranscriptionJobStatus"]

            if job_status == "COMPLETED":
                transcript_uri = status["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
                break
            elif job_status == "FAILED":
                reason = status["TranscriptionJob"].get("FailureReason", "Unknown")
                # Cleanup
                self._cleanup_job(transcribe_client, s3, bucket_name, s3_key, job_name)
                raise RuntimeError(f"AWS Transcribe job failed: {reason}")
        else:
            self._cleanup_job(transcribe_client, s3, bucket_name, s3_key, job_name)
            raise TimeoutError(f"AWS Transcribe job timed out after {max_wait}s")

        # Download result
        import urllib.request

        with urllib.request.urlopen(transcript_uri) as resp:
            result_json = json.loads(resp.read().decode())

        # Cleanup
        self._cleanup_job(transcribe_client, s3, bucket_name, s3_key, job_name)

        # Parse result
        return self._parse_transcribe_result(result_json, use_diarization)

    def _cleanup_job(self, transcribe_client, s3, bucket_name, s3_key, job_name):
        """Clean up S3 object and transcription job."""
        try:
            s3.delete_object(Bucket=bucket_name, Key=s3_key)
        except Exception:
            pass
        try:
            transcribe_client.delete_transcription_job(TranscriptionJobName=job_name)
        except Exception:
            pass

    def _parse_transcribe_result(
        self, result_json: dict, use_diarization: bool
    ) -> TranscribeResult:
        """Parse AWS Transcribe JSON output into TranscribeResult."""
        results = result_json.get("results", {})
        transcripts = results.get("transcripts", [])

        # Full text
        full_text = ""
        if transcripts:
            full_text = transcripts[0].get("transcript", "").strip()

        segments: list[TranscribeSegment] = []
        num_speakers = 0

        if use_diarization and "speaker_labels" in results:
            speaker_data = results["speaker_labels"]
            num_speakers = speaker_data.get("speakers", 0)

            # Map items to speaker labels
            speaker_segments_raw = speaker_data.get("segments", [])
            for seg in speaker_segments_raw:
                speaker_label = seg.get("speaker_label", "")
                seg_items = seg.get("items", [])
                seg_text_parts = []
                start_time = float(seg.get("start_time", 0))
                end_time = float(seg.get("end_time", 0))

                for item in seg_items:
                    content = item.get("content", "")
                    if content:
                        seg_text_parts.append(content)

                seg_text = " ".join(seg_text_parts).strip()
                if seg_text:
                    segments.append(
                        TranscribeSegment(
                            text=seg_text,
                            speaker_label=speaker_label,
                            start_time=start_time,
                            end_time=end_time,
                        )
                    )
        else:
            # No diarization — single segment
            if full_text:
                segments.append(TranscribeSegment(text=full_text))

        from .service import _is_hallucination

        if _is_hallucination(full_text):
            full_text = ""
            segments = []

        return TranscribeResult(
            text=full_text,
            segments=segments,
            num_speakers=num_speakers,
        )

    @staticmethod
    def _detect_format(audio_bytes: bytes, filename: str) -> str:
        """Detect audio format from bytes or filename."""
        if audio_bytes[:4] == b"RIFF":
            return "wav"
        if audio_bytes[:3] == b"ID3" or audio_bytes[:2] == b"\xff\xfb":
            return "mp3"
        if audio_bytes[:4] == b"OggS":
            return "ogg"
        if audio_bytes[:4] == b"fLaC":
            return "flac"
        # Fallback to filename extension
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
        return ext if ext in ("wav", "mp3", "ogg", "flac", "webm", "mp4") else "wav"

    @staticmethod
    def _detect_sample_rate(audio_bytes: bytes, media_format: str) -> int | None:
        """Try to detect sample rate from WAV header."""
        if media_format == "wav" and len(audio_bytes) > 44:
            try:
                buf = io.BytesIO(audio_bytes)
                with wave.open(buf, "rb") as wf:
                    return wf.getframerate()
            except Exception:
                pass
        return None
