"""Contract: the A3 code questions are answered from spring-petclinic's own code (the eval).

The live A3 check asks seven questions about spring-petclinic at ``b26f2352`` through REST hybrid
``knowledge_search`` and judges each answer: the hits must carry the known facts (``facts``) and
cite a file the answer is grounded in, every hit a pinned blob URL. Here the same questions and the
same judge run against the repository ingested the product's way (``knowledge_code_eval_support``),
with lexical retrieval only (no embedding space, no reranker), the baseline every Workspace has.

Numbers (lexical only, Evidence index double): before A3-green 1 of 7
questions and 7 of 20 facts; after it 6 of 7 (7 of 7 in some runs) and 18-20 of 20. Evidence keys
carry random revision ids, so a fetch that fills its cap returns a different identity window per
run; the bounds below hold across runs.
"""

from __future__ import annotations

import os

from tests.knowledge_code_eval_support import evaluate, ingest_petclinic, public_dns, summary

# The one A3 question lexical retrieval alone does not answer reliably, and why. "Which JPA entities
# exist ..., and how are Pet and Visit related?" needs the entity classes ``Vet`` and ``Specialty``,
# whose spans share only the word "entity" with the question, while the question's framing words
# ("exist", "related") are rare in code and lift SQL schema files. Meaning is the vector space's and
# the reranker's job; live retrieval runs both (hybrid search with reranking).
SEMANTIC_ONLY = frozenset({"entities"})
# Facts found across all questions, of 20.
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
