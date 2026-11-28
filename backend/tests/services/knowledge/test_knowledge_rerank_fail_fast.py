"""A reranker that is down no longer costs every search its timeouts."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from app.services.knowledge.embedding.port import EmbeddingError, EmbeddingState
from app.services.knowledge.rerank import availability
from app.services.knowledge.rerank import client as rerank_client
from app.services.knowledge.rerank.bedrock import RerankScore
from app.services.knowledge.rerank.catalog import RerankerSpec
from app.services.knowledge.retrieval import hybrid
from app.services.knowledge.retrieval.evidence import CitedEvidence
from app.services.knowledge.retrieval.hybrid import HybridEvidence

SPEC = RerankerSpec(
    key="test_reranker_v1", provider="bedrock", model="cohere.rerank-v3-5:0", data_policy_class="internal",
    max_documents=10, max_document_chars=2000, min_relevance=0.0,
)


class FakeReranker:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls = 0

    async def rerank(self, query: str, documents: list[str]):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return [RerankScore(index=index, relevance=1.0 - index / 10) for index in range(len(documents))]


def _hits() -> list[HybridEvidence]:
    return [
        HybridEvidence(
            CitedEvidence(evidence_key=f"k{n}", text=f"passage {n}", citation="c", revision_id="r", span_ordinal=n,
                          content_sha256="0" * 64, source_title="Doc", source_url=None),
            ("lexical",), 1.0 / (60 + n), None,
        )
        for n in (1, 2)
    ]


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    availability.reset_rerank_availability()

    async def admitted(*_args, **_kwargs):
        return None

    monkeypatch.setattr(hybrid, "admit_remote", admitted)
    yield
    availability.reset_rerank_availability()


async def _rerank(reranker: FakeReranker) -> tuple[list[HybridEvidence], dict[str, str]]:
    runtime = SimpleNamespace(reranker=SimpleNamespace(spec=SPEC, reranker=reranker))
    authorized = SimpleNamespace(admission_project_id="ws-1")
    states: dict[str, str] = {}
    ranked = await hybrid._reranked(None, runtime, authorized, "query", _hits(), states)
    return ranked, states


async def test_after_an_unavailable_reranker_the_next_searches_skip_it_visibly(monkeypatch) -> None:
    down = FakeReranker(EmbeddingError(EmbeddingState.UNAVAILABLE, "provider_failed"))
    ranked, states = await _rerank(down)
    assert states["rerank"] == "unavailable" and [hit.evidence.evidence_key for hit in ranked] == ["k1", "k2"]
    ranked, states = await _rerank(down)
    assert down.calls == 1, "skipped without waiting for it again"
    assert states["rerank"] == "unavailable", "a skipped rerank reads exactly like a failed one"
    assert [hit.evidence.evidence_key for hit in ranked] == ["k1", "k2"], "the fused order stands"

    clock = {"now": availability._now() + availability.SUSPEND_SECONDS + 1}
    monkeypatch.setattr(availability, "_now", lambda: clock["now"])
    up = FakeReranker(None)
    _, states = await _rerank(up)
    assert up.calls == 1 and states["rerank"] == "ok", "after the window it is tried again"
    assert not availability.rerank_suspended(SPEC.key)


async def test_other_failures_do_not_suspend_the_reranker() -> None:
    broken = FakeReranker(EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "provider_response"))
    _, states = await _rerank(broken)
    _, states = await _rerank(broken)
    assert broken.calls == 2 and states["rerank"] == "contract_violation"


def test_the_reranker_client_fails_fast(monkeypatch) -> None:
    captured = {}

    class Config:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.client = lambda name, config: ("client", name, config)
    fake_config = types.ModuleType("botocore.config")
    fake_config.Config = Config
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore.config", fake_config)
    monkeypatch.setattr(rerank_client, "bedrock_runtime_hold", lambda region: None)

    built = rerank_client.build_reranker_client("eu-central-1")

    assert built[1] == "bedrock-runtime"
    assert captured["connect_timeout"] == 2 and captured["read_timeout"] == 8
    assert captured["retries"] == {"max_attempts": 1, "mode": "standard"}
