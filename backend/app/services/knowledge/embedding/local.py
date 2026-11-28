"""In-process embeddings from a pinned, offline model artifact (``fastembed`` / ONNX). Nothing is downloaded: a missing
or altered artifact is ``needs_configuration``."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import warnings
from pathlib import Path
from typing import Any

from .catalog import EmbeddingProvider, EmbeddingSpace
from .port import EmbeddingError, EmbeddingPurpose, EmbeddingState, checked_inputs, checked_vectors

logger = logging.getLogger(__name__)
_HASH_CHUNK_BYTES = 1024 * 1024


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(space: EmbeddingSpace, model_root: Path) -> Path:
    directory = model_root / space.key
    if not directory.is_dir():
        raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, "model_artifact_missing")
    for name, expected in space.artifact_files.items():
        path = directory / name
        if not path.is_file() or _file_sha256(path) != expected:
            raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, "model_artifact_mismatch")
    return directory


class LocalEmbedder:
    def __init__(self, space: EmbeddingSpace, *, model_root: Path) -> None:
        if space.provider is not EmbeddingProvider.LOCAL:
            raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "provider")
        self.space = space
        self._model_root = model_root
        self._model: Any | None = None
        self._lock = asyncio.Lock()

    def _load(self) -> Any:
        directory = verify_artifact(self.space, self._model_root)
        try:
            from fastembed import TextEmbedding
        except ImportError:
            raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, "runtime_missing") from None
        try:
            with warnings.catch_warnings():
                # fastembed announces that this model family now uses mean pooling. That is the
                # reference pooling of these sentence-transformers models, so the notice is expected.
                warnings.filterwarnings("ignore", message=".*now uses mean pooling.*", category=UserWarning)
                return TextEmbedding(
                    self.space.model,
                    specific_model_path=str(directory),
                    local_files_only=True,
                    lazy_load=False,
                )
        except Exception:
            # The library message may carry paths; only the fixed state leaves this module.
            logger.warning("Local embedding model failed to load: space=%s", self.space.key)
            raise EmbeddingError(EmbeddingState.UNAVAILABLE, "model_load_failed") from None

    async def _model_instance(self) -> Any:
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load)
        return self._model

    async def embed(self, texts: list[str], purpose: EmbeddingPurpose) -> list[list[float]]:
        prepared = checked_inputs(self.space, texts, purpose)
        model = await self._model_instance()
        try:
            raw = await asyncio.to_thread(lambda: [vector.tolist() for vector in model.embed(prepared)])
        except Exception:
            logger.warning("Local embedding failed: space=%s texts=%d", self.space.key, len(prepared))
            raise EmbeddingError(EmbeddingState.UNAVAILABLE, "inference_failed") from None
        return checked_vectors(self.space, raw, len(prepared))


__all__ = ["LocalEmbedder", "verify_artifact"]
