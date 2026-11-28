"""Bounded lexical recall beyond the identity window."""

from __future__ import annotations

import pytest

from app.services.knowledge.evidence_index.operations import (
    OPERATIONS,
    SEARCH_EVIDENCE_LEXICAL,
    SEARCH_EVIDENCE_LEXICAL_PAIR,
    OperationKind,
    operation,
)
from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.knowledge.ingestion.spans import derive_evidence_key
from app.services.knowledge.retrieval.errors import KnowledgeStoreContractError
from app.services.knowledge.retrieval.index_query_store import EvidenceIndexQueryStore
from app.services.knowledge.retrieval.lexical_ranking import rank_candidates
from app.services.knowledge.retrieval.lexical_recall import (
    MAX_CANDIDATES,
    MAX_FETCH_TERMS,
    MAX_FETCHES,
    MAX_PAIR_FETCHES,
    MAX_SINGLE_FETCHES,
    LexicalFetch,
    candidate_cap,
    fetch_plan,
    fetch_terms,
    pair_plan,
    ranking_terms,
)
from tests.services.knowledge.retrieval.knowledge_lexical_recall_support import (
    BEST_REVISION,
    COMMON_REVISION,
    FILLER_PER_TERM,
    LIMIT,
    _corpus,
    _request,
    _workspace,
)
from tests.support.knowledge_evidence_index_support import FakeEvidenceIndex


def _best_keys(best: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(derive_evidence_key(BEST_REVISION, index) for index, _ in enumerate(best, start=1))


def _prepared(best: tuple[str, ...]) -> tuple[FakeEvidenceIndex, WorkspaceId, EvidenceIndexQueryStore]:
    evidence_index = FakeEvidenceIndex()
    workspace = _workspace()
    spans = _corpus(best)
    evidence_index.seed_evidence(workspace.canonical, spans)
    assert len(spans) == 2 * FILLER_PER_TERM + len(best) > MAX_CANDIDATES
    store = EvidenceIndexQueryStore(evidence_index)
    return evidence_index, workspace, store


async def _old_window(evidence_index: FakeEvidenceIndex, workspace: WorkspaceId, query_text: str) -> tuple[str, ...]:
    rows = evidence_index._search(
        evidence_index.workspace_records(workspace.canonical),
        {"term": query_text, "principals": ["public"], "cap": candidate_cap(LIMIT)},
    )
    return tuple(str(row["evidence_key"]) for row in rows)


async def test_a_selective_term_reaches_the_best_spans_outside_the_identity_window():
    best = ("alpha beta gamma together one", "alpha beta gamma together two")
    evidence_index, workspace, store = _prepared(best)
    expected = _best_keys(best)

    window = await _old_window(evidence_index, workspace, "alpha beta gamma")
    assert len(window) == MAX_CANDIDATES
    assert not set(window) & set(expected)

    evidence = await store.search_lexical(_request(workspace, "alpha beta gamma"))

    assert tuple(item.evidence_id for item in evidence[:2]) == expected
    assert len(evidence) == LIMIT


async def test_a_conjunction_reaches_the_best_spans_when_every_term_is_over_the_cap():
    best = ("alpha beta together one", "alpha beta together two")
    evidence_index, workspace, store = _prepared(best)
    expected = _best_keys(best)

    # Neither single-term window contains a best span: 70 lower-keyed spans plus the
    # two best exceed the cap for "alpha" and for "beta" alike.
    for term in ("alpha", "beta"):
        window = await _old_window(evidence_index, workspace, term)
        assert len(window) == MAX_CANDIDATES
        assert not set(window) & set(expected)

    evidence = await store.search_lexical(_request(workspace, "alpha beta"))

    assert tuple(item.evidence_id for item in evidence[:2]) == expected
    assert evidence_index.operation_keys().count(SEARCH_EVIDENCE_LEXICAL_PAIR) == 1


async def test_a_single_term_query_costs_exactly_one_fetch():
    evidence_index, workspace, store = _prepared(("alpha beta together one",))

    evidence = await store.search_lexical(_request(workspace, "alpha"))

    assert evidence_index.operation_keys() == [SEARCH_EVIDENCE_LEXICAL]
    assert len(evidence) == LIMIT


async def test_the_plan_is_bounded_and_independent_of_the_corpus_size():
    best = ("alpha beta together one",)
    evidence_index, workspace, store = _prepared(best)
    database = workspace.canonical

    await store.search_lexical(_request(workspace, "alpha beta"))
    small = len(evidence_index.requests)
    assert small == 3

    evidence_index.seed_evidence(
        database,
        {derive_evidence_key(COMMON_REVISION, 1000 + index): f"alpha beta bulk {index}" for index in range(900)},
    )
    evidence_index.requests.clear()
    await store.search_lexical(_request(workspace, "alpha beta"))

    assert len(evidence_index.requests) == small
    # Every fetch stayed inside its own server-owned cap, so nothing materialized the
    # corpus: 1042 records match, and no response carried more than 64 rows.
    assert all(params["cap"] == MAX_CANDIDATES for _, _, params in evidence_index.requests)


async def test_more_terms_than_the_fetch_budget_still_bound_the_plan():
    evidence_index, workspace, store = _prepared(("alpha beta together one",))

    await store.search_lexical(_request(workspace, "alpha beta gamma delta epsilon zeta eta theta"))

    assert len(evidence_index.requests) == MAX_FETCH_TERMS + 1 <= MAX_FETCHES
    assert set(evidence_index.operation_keys()) <= set(OPERATIONS)
    assert {params.get("term") for _, _, params in evidence_index.requests} >= {"alpha", "zeta"}
    assert not {"eta", "theta"} & {params.get("term") for _, _, params in evidence_index.requests}


async def test_a_selective_term_costs_no_pair_fetch():
    evidence_index, workspace, store = _prepared(("alpha gamma together one",))

    evidence = await store.search_lexical(_request(workspace, "alpha gamma"))

    assert evidence_index.operation_keys() == [SEARCH_EVIDENCE_LEXICAL] * 2
    assert evidence[0].evidence_id == _best_keys(("alpha gamma together one",))[0]


def test_the_plan_names_only_registered_operations_and_their_declared_parameters():
    singles = fetch_plan("alpha beta gamma delta epsilon")
    pairs = pair_plan(singles, [True] * len(singles))

    assert [len(fetch.terms) for fetch in singles] == [1] * 5
    assert len(pairs) == MAX_PAIR_FETCHES and all(len(fetch.terms) == 2 for fetch in pairs)
    for fetch in (*singles, *pairs):
        spec = operation(fetch.operation)
        assert spec.kind is OperationKind.READ
        assert frozenset(fetch.parameters(MAX_CANDIDATES)) == spec.parameters
    query = "alpha beta gamma delta epsilon zeta eta"
    assert fetch_terms(query) == ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
    assert ranking_terms(query)[-1] == "eta"


def test_a_plural_is_also_fetched_by_its_singular_and_bounded():
    plan = fetch_plan("entities pets classes caches")

    assert [fetch.terms[0] for fetch in plan] == [
        "entities", "entity", "pets", "pet", "classes", "class", "caches", "cache",
    ]
    assert len(fetch_plan(" ".join(f"word{i}s" for i in range(9)))) == MAX_SINGLE_FETCHES


def test_a_fetch_outside_the_registered_arities_is_refused():
    for terms in ((), ("a", "b", "c"), ("a", ""), "alpha"):
        with pytest.raises(KnowledgeStoreContractError):
            LexicalFetch(terms)  # type: ignore[arg-type]


def test_one_spelling_of_a_term_spends_one_fetch():
    assert fetch_terms("Alpha alpha ALPHA beta") == ("Alpha", "beta")
    assert fetch_plan("Alpha alpha") == (LexicalFetch(("Alpha",), serves="alpha"),)


def test_ranking_does_not_depend_on_the_order_the_fetches_completed_in():
    terms = ranking_terms("alpha beta")
    forward = {"k1": "alpha only", "k2": "alpha beta", "k3": "beta only"}
    reverse = {"k3": "beta only", "k2": "alpha beta", "k1": "alpha only"}

    assert rank_candidates(forward, terms) == rank_candidates(reverse, terms)
    assert [key for key, _ in rank_candidates(forward, terms)] == ["k2", "k1", "k3"]


async def test_the_same_corpus_and_query_always_produce_the_same_sequence():
    _, workspace, store = _prepared(("alpha beta together one", "alpha beta together two"))

    runs = [
        tuple((item.evidence_id, item.text) for item in await store.search_lexical(_request(workspace, "alpha beta")))
        for _ in range(3)
    ]

    assert runs[0] == runs[1] == runs[2]
    assert len({key for key, _ in runs[0]}) == len(runs[0])


async def test_every_fetch_of_the_plan_targets_only_its_own_workspace():
    evidence_index, workspace, store = _prepared(("alpha beta together one",))

    await store.search_lexical(_request(workspace, "alpha beta"))

    assert {project for _, project, _ in evidence_index.requests} == {workspace.canonical}
    assert {operation(key).kind for key in evidence_index.operation_keys()} == {OperationKind.READ}


async def test_query_text_without_a_word_token_reaches_no_fetch_at_all():
    evidence_index, workspace, store = _prepared(("alpha beta together one",))

    assert await store.search_lexical(_request(workspace, "* - ( ) !")) == ()
    assert evidence_index.requests == []
