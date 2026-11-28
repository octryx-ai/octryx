"""A failing fetch fails the whole request, the first failure in plan order is reported, and an index that ignores the cap is a contract violation."""

from __future__ import annotations

import pytest

from app.services.knowledge.evidence_index.errors import EvidenceIndexUnavailableError
from app.services.knowledge.retrieval.contracts import RetrievalMode
from app.services.knowledge.retrieval.errors import KnowledgeIndexUnavailableError, KnowledgeStoreContractError
from app.services.knowledge.retrieval.index_query_store import EvidenceIndexQueryStore
from app.services.knowledge.retrieval.lexical_recall import MAX_CANDIDATES, fetch_plan
from tests.services.knowledge.retrieval.knowledge_lexical_recall_support import _corpus, _request, _workspace
from tests.support.knowledge_evidence_index_support import FakeEvidenceIndex


def _term_failures(behaviour: dict[str, str]):
    def intercept(key, params):
        mode = behaviour.get(str(params.get("term", "")))
        if mode == "unavailable":
            raise EvidenceIndexUnavailableError()
        if mode == "malformed":
            return ({"evidence_key": "0a:1", "body_text": 7},)
        return None

    return intercept


def _seeded() -> tuple[FakeEvidenceIndex, object]:
    evidence_index = FakeEvidenceIndex()
    workspace = _workspace()
    evidence_index.seed_evidence(workspace.canonical, _corpus(("alpha beta together one",)))
    return evidence_index, workspace


async def test_one_failing_fetch_fails_the_whole_request():
    evidence_index, workspace = _seeded()

    def intercept(key, params):
        if "term_a" in params:
            raise EvidenceIndexUnavailableError()
        return None

    evidence_index.intercept = intercept
    store = EvidenceIndexQueryStore(evidence_index)
    with pytest.raises(KnowledgeIndexUnavailableError) as failure:
        await store.search_lexical(_request(workspace, "alpha beta"))
    assert failure.value.mode == RetrievalMode.LEXICAL.value


@pytest.mark.parametrize(
    ("alpha", "beta", "reported"),
    [
        ("unavailable", "malformed", KnowledgeIndexUnavailableError),
        ("malformed", "unavailable", KnowledgeStoreContractError),
    ],
)
async def test_the_reported_failure_is_the_first_in_plan_order_not_the_stricter_kind(
    alpha: str, beta: str, reported: type[Exception]
):
    plan = fetch_plan("alpha beta")
    assert [fetch.terms for fetch in plan[:2]] == [("alpha",), ("beta",)]
    evidence_index, workspace = _seeded()
    evidence_index.intercept = _term_failures({"alpha": alpha, "beta": beta})
    store = EvidenceIndexQueryStore(evidence_index)

    with pytest.raises(reported) as failure:
        await store.search_lexical(_request(workspace, "alpha beta"))

    assert type(failure.value) is reported


async def test_an_index_that_ignores_the_cap_is_a_contract_violation():
    evidence_index, workspace = _seeded()

    def intercept(key, params):
        records = evidence_index.workspace_records(workspace.canonical)
        return evidence_index._search(records, {**params, "cap": MAX_CANDIDATES + 1})

    evidence_index.intercept = intercept
    store = EvidenceIndexQueryStore(evidence_index)
    with pytest.raises(KnowledgeStoreContractError):
        await store.search_lexical(_request(workspace, "alpha beta"))
