"""Contract: the A3 code questions are answered from spring-petclinic's own code (the eval)."""

from __future__ import annotations

import os

from tests.services.knowledge.knowledge_code_eval_support import evaluate, ingest_petclinic, public_dns, summary

# Lexical retrieval alone misses this one: ``Vet`` and ``Specialty`` share only "entity" with the question, whose
# framing words lift SQL schema files instead. Live retrieval adds vectors and a reranker for it.
SEMANTIC_ONLY = frozenset({"entities"})
REQUIRED_FACTS = 18


async def test_the_a3_code_questions_are_answered_from_the_repository(db, monkeypatch) -> None:
    public_dns(monkeypatch)
    ingested = await ingest_petclinic(db)

    scores = await evaluate(db, ingested)

    if os.environ.get("OCTRYX_EVAL_REPORT"):
        print("\n" + summary(scores))
    failed = {score.key for score in scores if not score.ok}
    assert failed <= SEMANTIC_ONLY, summary(scores)
    found = sum(score.facts_total - len(score.facts_missing) for score in scores)
    assert found >= REQUIRED_FACTS, summary(scores)
