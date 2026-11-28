"""The local query embedder is warmed in the background at startup."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services.knowledge.embedding import warmup
from app.services.knowledge.embedding.catalog import EmbeddingProvider
from app.services.knowledge.embedding.port import EmbeddingError, EmbeddingPurpose, EmbeddingState

pytestmark = pytest.mark.asyncio


class FakeEmbedder:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], EmbeddingPurpose]] = []
        self.error = error

    async def embed(self, texts, purpose):
        self.calls.append((texts, purpose))
        if self.error is not None:
            raise self.error
        return [[0.0]]


def _runtime(provider: EmbeddingProvider, embedder: FakeEmbedder):
    return SimpleNamespace(space=SimpleNamespace(key="local_test", provider=provider), embedder=embedder)


async def test_a_local_embedder_is_exercised_once_with_a_query():
    embedder = FakeEmbedder()
    assert await warmup.warm_embedder(_runtime(EmbeddingProvider.LOCAL, embedder)) is True
    assert embedder.calls == [([warmup.WARMUP_TEXT], EmbeddingPurpose.QUERY)]


async def test_remote_or_missing_spaces_are_not_warmed():
    embedder = FakeEmbedder()
    assert await warmup.warm_embedder(_runtime(EmbeddingProvider.BEDROCK, embedder)) is False
    assert await warmup.warm_embedder(None) is False
    assert embedder.calls == []


async def test_a_failing_warm_up_never_raises_and_logs_a_fixed_state(caplog):
    failing = FakeEmbedder(EmbeddingError(EmbeddingState.UNAVAILABLE, "model_load_failed"))
    assert await warmup.warm_embedder(_runtime(EmbeddingProvider.LOCAL, failing)) is False
    broken = FakeEmbedder(RuntimeError("/secret/path"))
    assert await warmup.warm_embedder(_runtime(EmbeddingProvider.LOCAL, broken)) is False
    assert "/secret/path" not in caplog.text
    assert "state=unavailable" in caplog.text and "state=unexpected" in caplog.text


async def test_the_start_does_not_wait_for_the_warm_up():
    release = asyncio.Event()

    class SlowEmbedder(FakeEmbedder):
        async def embed(self, texts, purpose):
            await release.wait()
            return await super().embed(texts, purpose)

    embedder = SlowEmbedder()
    task = warmup.start_embedder_warmup(lambda: _runtime(EmbeddingProvider.LOCAL, embedder))
    assert not task.done()
    release.set()
    assert await task is True


async def test_without_a_configured_space_nothing_is_built(monkeypatch):
    monkeypatch.delenv(warmup.SPACE_ENV, raising=False)
    assert warmup._configured_embedding() is None
