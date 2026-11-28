"""In-process embedding driver (fastembed / sentence-transformers)."""

from __future__ import annotations

from collections.abc import Callable

from ...error_facts import error_type
from .base import FAMILY_IN_PROCESS, BaseEmbeddingDriver, EmbeddingConfigurationError


class InProcessEmbeddingDriver(BaseEmbeddingDriver):
    provider_id = FAMILY_IN_PROCESS

    def __init__(self, *, model: str, version: str) -> None:
        self.model = model
        self.version = version
        self._backend: str | None = None
        self._encode: Callable[[list[str]], list[list[float]]] | None = None
        self._ensure_backend()

    def _ensure_backend(self) -> None:
        encode = _try_fastembed(self.model)
        if encode is not None:
            self._encode, self._backend = encode, "fastembed"
            return
        encode = _try_sentence_transformers(self.model)
        if encode is not None:
            self._encode, self._backend = encode, "sentence_transformers"
            return
        raise EmbeddingConfigurationError(
            "In-process embeddings require 'fastembed' or 'sentence-transformers'. "
            "Install the 'knowledge' extra, or configure a different embedding provider."
        )

    def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        assert self._encode is not None  # set by _ensure_backend
        prepared = [self._prepare(text, is_query=is_query) for text in texts]
        return self._encode(prepared)

    def _prepare(self, text: str, *, is_query: bool) -> str:
        # E5-family models are asymmetric: queries and passages need explicit
        # prefixes, otherwise retrieval quality degrades noticeably.
        if "e5" in self.model.lower():
            return ("query: " if is_query else "passage: ") + text
        return text


def _try_fastembed(model: str) -> Callable[[list[str]], list[list[float]]] | None:
    try:
        from fastembed import TextEmbedding
    except Exception:
        return None
    try:
        embedder = TextEmbedding(model_name=model)
    except Exception as exc:
        raise EmbeddingConfigurationError(
            f"fastembed could not load model '{model}' (error_type={error_type(exc)})."
        ) from exc

    def _encode(texts: list[str]) -> list[list[float]]:
        return [[float(value) for value in vector] for vector in embedder.embed(texts)]

    return _encode


def _try_sentence_transformers(model: str) -> Callable[[list[str]], list[list[float]]] | None:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None
    try:
        embedder = SentenceTransformer(model)
    except Exception as exc:
        raise EmbeddingConfigurationError(
            f"sentence-transformers could not load model '{model}' (error_type={error_type(exc)})."
        ) from exc

    def _encode(texts: list[str]) -> list[list[float]]:
        vectors = embedder.encode(texts, normalize_embeddings=True)
        return [[float(value) for value in row] for row in vectors]

    return _encode
