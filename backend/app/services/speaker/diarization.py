"""Speaker Diarization & Identification Service."""

from __future__ import annotations

import io
import logging
import os
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..error_facts import error_text
from ..person_log_ref import person_log_ref

if TYPE_CHECKING:
    import numpy as np
    import torch

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

try:
    import torch
except ImportError:
    torch = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Lazy-loaded models (heavy, load once)
_diarization_pipeline = None
_embedding_model = None
_HF_TOKEN: str | None = os.environ.get("HF_TOKEN")


def set_hf_token(token: str) -> None:
    global _HF_TOKEN
    _HF_TOKEN = token


def _get_diarization_pipeline():
    if np is None or torch is None:
        raise RuntimeError(
            "numpy and torch are required for speaker diarization. Install with: pip install octryx[speaker]"
        )
    global _diarization_pipeline
    if _diarization_pipeline is None:
        from pyannote.audio import Pipeline

        logger.info("Loading pyannote speaker-diarization pipeline...")
        _diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=_HF_TOKEN,
        )
        # Use CPU (MPS has issues with pyannote)
        _diarization_pipeline.to(torch.device("cpu"))
        logger.info("Diarization pipeline loaded.")
    return _diarization_pipeline


def _get_embedding_model():
    if np is None or torch is None:
        raise RuntimeError(
            "numpy and torch are required for speaker embedding. Install with: pip install octryx[speaker]"
        )
    global _embedding_model
    if _embedding_model is None:
        from pyannote.audio import Inference, Model

        logger.info("Loading pyannote speaker embedding model...")
        model = Model.from_pretrained(
            "pyannote/wespeaker-voxceleb-resnet34-LM",
            token=_HF_TOKEN,
        )
        _embedding_model = Inference(model, window="whole")
        logger.info("Speaker embedding model loaded.")
    return _embedding_model


@dataclass
class SpeakerSegment:
    start_sec: float
    end_sec: float
    speaker_label: str  # "SPEAKER_00", "SPEAKER_01" or enrolled name
    speaker_name: str | None = None  # Resolved name from enrollment
    text: str = ""  # Filled after STT alignment


@dataclass
class DiarizationResult:
    segments: list[SpeakerSegment] = field(default_factory=list)
    num_speakers: int = 0
    embeddings: dict[str, np.ndarray] = field(default_factory=dict)  # label -> embedding


@dataclass
class SpeakerProfile:
    name: str
    embedding: np.ndarray  # 256-dim vector
    project_id: str
    enrolled_at: str = ""


# In-memory speaker profile store (per project)
_speaker_profiles: dict[str, list[SpeakerProfile]] = {}  # project_id -> profiles

# Persistence file path for speaker profiles
_PROFILES_FILE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "speaker_profiles.json"


def _persist_profiles() -> None:
    import json

    try:
        _PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, list[dict]] = {}
        for project_id, profiles in _speaker_profiles.items():
            data[project_id] = [
                {
                    "name": p.name,
                    "embedding": p.embedding.tolist(),
                    "project_id": p.project_id,
                    "enrolled_at": p.enrolled_at,
                }
                for p in profiles
            ]
        _PROFILES_FILE.write_text(json.dumps(data, indent=2))
        logger.info("Persisted %d speaker profiles to %s", sum(len(v) for v in data.values()), _PROFILES_FILE)
    except Exception as e:
        logger.warning("Failed to persist speaker profiles: %s", error_text("speaker_profiles_persist_failed", e))


def _load_profiles() -> None:
    import json

    global _speaker_profiles
    if not _PROFILES_FILE.exists():
        return
    try:
        data = json.loads(_PROFILES_FILE.read_text())
        for project_id, profiles in data.items():
            _speaker_profiles[project_id] = [
                SpeakerProfile(
                    name=p["name"],
                    embedding=np.array(p["embedding"], dtype=np.float32),
                    project_id=p["project_id"],
                    enrolled_at=p.get("enrolled_at", ""),
                )
                for p in profiles
            ]
        total = sum(len(v) for v in _speaker_profiles.values())
        logger.info("Loaded %d speaker profiles from %s", total, _PROFILES_FILE)
    except Exception as e:
        logger.warning("Failed to load speaker profiles: %s", error_text("speaker_profiles_load_failed", e))


# Auto-load on module import
_load_profiles()


def enroll_speaker(name: str, audio_bytes: bytes, project_id: str) -> SpeakerProfile:
    embedding_model = _get_embedding_model()

    # Convert bytes to the format pyannote expects
    waveform, sample_rate = _load_audio(audio_bytes)

    # Extract embedding
    embedding = embedding_model({"waveform": waveform, "sample_rate": sample_rate})
    # Handle different return types from pyannote (tensor vs memoryview)
    if hasattr(embedding, "data") and hasattr(embedding.data, "cpu"):
        embedding_np = embedding.data.cpu().numpy().flatten()
    elif hasattr(embedding, "data"):
        embedding_np = np.array(embedding.data).flatten()
    else:
        embedding_np = np.array(embedding).flatten()

    from ...time_utils import utc_now

    profile = SpeakerProfile(
        name=name,
        embedding=embedding_np,
        project_id=project_id,
        enrolled_at=str(utc_now()),
    )

    # Store in memory
    if project_id not in _speaker_profiles:
        _speaker_profiles[project_id] = []

    # Remove existing profile with same name
    _speaker_profiles[project_id] = [p for p in _speaker_profiles[project_id] if p.name != name]
    _speaker_profiles[project_id].append(profile)

    # Persist to disk so profiles survive server restarts
    _persist_profiles()

    logger.info("Enrolled speaker %s for project %s", person_log_ref(name), project_id)
    return profile


def get_enrolled_speakers(project_id: str) -> list[SpeakerProfile]:
    return _speaker_profiles.get(project_id, [])


def identify_speaker(
    embedding: np.ndarray,
    project_id: str,
    threshold: float = 0.55,
) -> str | None:
    profiles = _speaker_profiles.get(project_id, [])
    if not profiles:
        return None

    best_name = None
    best_score = -1.0

    for profile in profiles:
        score = _cosine_similarity(embedding, profile.embedding)
        if score > best_score:
            best_score = score
            best_name = profile.name

    if best_score >= threshold:
        return best_name
    return None


async def diarize_audio(
    audio_bytes: bytes,
    project_id: str | None = None,
    num_speakers: int | None = None,
) -> DiarizationResult:
    import asyncio

    # Run in thread pool since pyannote is CPU-intensive
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _diarize_sync, audio_bytes, project_id, num_speakers)


def _diarize_sync(
    audio_bytes: bytes,
    project_id: str | None = None,
    num_speakers: int | None = None,
) -> DiarizationResult:
    pipeline = _get_diarization_pipeline()
    embedding_model = _get_embedding_model()

    waveform, sample_rate = _load_audio(audio_bytes)
    audio_input = {"waveform": waveform, "sample_rate": sample_rate}

    # Run diarization
    kwargs: dict[str, Any] = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = num_speakers

    diarization = pipeline(audio_input, **kwargs)

    # pyannote 4.x returns DiarizeOutput; extract the Annotation object
    if hasattr(diarization, "speaker_diarization"):
        annotation = diarization.speaker_diarization
        precomputed_embeddings = diarization.speaker_embeddings  # numpy array (n_speakers, 256)
    else:
        # pyannote 3.x returns Annotation directly
        annotation = diarization
        precomputed_embeddings = None

    # Extract segments
    segments: list[SpeakerSegment] = []
    speaker_labels: set[str] = set()

    for turn, _, speaker in annotation.itertracks(yield_label=True):
        speaker_labels.add(speaker)
        segments.append(
            SpeakerSegment(
                start_sec=turn.start,
                end_sec=turn.end,
                speaker_label=speaker,
            )
        )

    # Extract embeddings for each speaker
    embeddings: dict[str, np.ndarray] = {}

    # pyannote 4.x provides precomputed embeddings (n_speakers x 256)
    if precomputed_embeddings is not None and len(precomputed_embeddings) > 0:
        sorted_labels = sorted(speaker_labels)
        for i, label in enumerate(sorted_labels):
            if i < len(precomputed_embeddings):
                embeddings[label] = precomputed_embeddings[i]
        logger.info("Using precomputed embeddings for %d speakers", len(embeddings))
    else:
        logger.info(
            "No precomputed embeddings (shape=%s), computing manually...",
            precomputed_embeddings.shape if precomputed_embeddings is not None else None,
        )

    # Fallback: compute embeddings manually if not provided or empty
    if not embeddings:
        for speaker_label in speaker_labels:
            # Get the longest segment for this speaker (best embedding quality)
            speaker_segs = [s for s in segments if s.speaker_label == speaker_label]
            if not speaker_segs:
                continue
            longest = max(speaker_segs, key=lambda s: s.end_sec - s.start_sec)

            # Extract embedding from that segment
            start_sample = int(longest.start_sec * sample_rate)
            end_sample = int(longest.end_sec * sample_rate)
            segment_waveform = waveform[:, start_sample:end_sample]

            logger.info(
                "Speaker %s: segment %.2f-%.2fs, waveform samples=%d (need >%d)",
                speaker_label,
                longest.start_sec,
                longest.end_sec,
                segment_waveform.shape[1],
                int(sample_rate * 0.5),
            )

            if segment_waveform.shape[1] > sample_rate * 0.5:  # At least 0.5s
                emb = embedding_model({"waveform": segment_waveform, "sample_rate": sample_rate})
                if hasattr(emb, "data") and hasattr(emb.data, "cpu"):
                    embeddings[speaker_label] = emb.data.cpu().numpy().flatten()
                elif hasattr(emb, "data"):
                    embeddings[speaker_label] = np.array(emb.data).flatten()
                else:
                    embeddings[speaker_label] = np.array(emb).flatten()
                logger.info("Extracted embedding for %s: shape=%s", speaker_label, embeddings[speaker_label].shape)

    # Try to identify speakers if project has enrolled profiles
    if project_id:
        for seg in segments:
            if seg.speaker_label in embeddings:
                name = identify_speaker(embeddings[seg.speaker_label], project_id)
                logger.info("identify_speaker(%s) -> %s", seg.speaker_label, person_log_ref(name) if name else None)
                if name:
                    seg.speaker_name = name

    return DiarizationResult(
        segments=segments,
        num_speakers=len(speaker_labels),
        embeddings=embeddings,
    )


def _load_audio(audio_bytes: bytes) -> tuple[torch.Tensor, int]:
    buf = io.BytesIO(audio_bytes)
    with wave.open(buf, "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    # Convert to float32 tensor
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    # Shape: (1, num_samples) for pyannote
    waveform = torch.from_numpy(samples).unsqueeze(0)
    return waveform, sample_rate


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
