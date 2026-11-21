"""Subclassed or mutated requests and evidence never cross the store boundary, and a store mutating its request or an earlier clone cannot alter the bundle snapshot."""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge.objects.source_object import SourceObjectRef
from app.services.knowledge.retrieval.contracts import (
    MAX_LIMIT_PER_MODE,
    Evidence,
    EvidenceKind,
    RetrievalMode,
    RetrievalRequest,
)
from app.services.knowledge.retrieval.errors import (
    InvalidRetrievalRequestError,
    InvalidWorkspaceError,
    KnowledgeStoreContractError,
    WorkspaceRequiredError,
)
from app.services.knowledge.retrieval.facade import retrieve_bundle
from tests.knowledge_retrieval_facade_support import OTHER_WS, WS, FakeStore, _assert_closed, _evidence, _request

# --- Untrusted contract instances ------------------------------------------------


class UncheckedRequest(RetrievalRequest):
    """Subclass skipping validation: must not reach a store."""

    __slots__ = ()

    def __post_init__(self) -> None:
        pass


class UncheckedEvidence(Evidence):
    __slots__ = ()

    def __post_init__(self) -> None:
        pass


class UncheckedSource(SourceObjectRef):
    __slots__ = ()

    def __post_init__(self) -> None:
        pass


def _mutated(obj, **fields):
    for name, value in fields.items():
        object.__setattr__(obj, name, value)
    return obj


def _source() -> SourceObjectRef:
    return SourceObjectRef(bucket="kb-docs", key="team/orders.md")


def _sourced_evidence(source: SourceObjectRef, mode: RetrievalMode = RetrievalMode.VECTOR) -> Evidence:
    return Evidence(workspace=WS, evidence_id="chunk:1", mode=mode, kind=EvidenceKind.PASSAGE, text="t", source=source)


def _with_mutated_source() -> Evidence:
    item = _sourced_evidence(_source())
    _mutated(item.source, key="../secrets.md")
    return item


class MutatingStore(FakeStore):
    """Widens its request in place and returns foreign, over-limit evidence."""

    async def _search(self, mode, request):
        self.calls.append((mode, request))
        _mutated(request, workspace=OTHER_WS, limit_per_mode=MAX_LIMIT_PER_MODE)
        return [_evidence(f"chunk:{i}", mode, workspace=OTHER_WS) for i in range(5)]


class SilentMutatingStore(FakeStore):
    """Returns valid evidence but mutates the nested workspace of its request."""

    async def _search(self, mode, request):
        self.calls.append((mode, request))
        _mutated(request.workspace, value=OTHER_WS.value)
        return []


class LateMutatingStore(FakeStore):
    """Mutates the request of an earlier call after that call returned."""

    async def _search(self, mode, request):
        for _, earlier in self.calls:
            _mutated(earlier, limit_per_mode=MAX_LIMIT_PER_MODE)
            _mutated(earlier.workspace, value=OTHER_WS.value)
        return await super()._search(mode, request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_obj",
    [
        UncheckedRequest(
            workspace=WS, query_text="orders", modes=frozenset({RetrievalMode.VECTOR}), limit_per_mode=10**6
        ),
        UncheckedRequest(workspace="*", query_text="orders", modes=frozenset({RetrievalMode.VECTOR}), limit_per_mode=3),
        _mutated(_request({RetrievalMode.VECTOR}), limit_per_mode=10**6),
        _mutated(_request({RetrievalMode.VECTOR}), modes={"cypher"}),
        _mutated(_request({RetrievalMode.VECTOR}), query_text="orders\u202eservice"),
    ],
)
async def test_subclassed_or_mutated_request_never_reaches_a_store(request_obj):
    store = FakeStore()
    with pytest.raises(InvalidRetrievalRequestError) as exc_info:
        await retrieve_bundle(store, request_obj)
    assert type(exc_info.value) is InvalidRetrievalRequestError
    _assert_closed(exc_info.value)
    assert store.calls == []


@pytest.mark.asyncio
async def test_request_with_mutated_workspace_is_denied():
    request = _request({RetrievalMode.VECTOR})
    _mutated(request.workspace, value=uuid.UUID(int=0))
    store = FakeStore()
    with pytest.raises(InvalidWorkspaceError) as exc_info:
        await retrieve_bundle(store, request)
    _assert_closed(exc_info.value)
    with pytest.raises(WorkspaceRequiredError):
        await retrieve_bundle(store, _mutated(_request({RetrievalMode.VECTOR}), workspace=None))
    assert store.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_item",
    [
        lambda: UncheckedEvidence(
            workspace=WS, evidence_id="#12:0", mode=RetrievalMode.VECTOR, kind=EvidenceKind.PASSAGE, text="a\u202eb"
        ),
        lambda: _mutated(_evidence("chunk:1", RetrievalMode.VECTOR), text="a\u202eb"),
        lambda: _mutated(_evidence("chunk:1", RetrievalMode.VECTOR), evidence_id="#12:0"),
        lambda: _mutated(_evidence("chunk:1", RetrievalMode.VECTOR), workspace=OTHER_WS.canonical),
        lambda: _mutated(_evidence("chunk:1", RetrievalMode.VECTOR), source=UncheckedSource(bucket="BAD", key="../x")),
        _with_mutated_source,
    ],
)
async def test_subclassed_or_mutated_evidence_is_rejected(make_item):
    store = FakeStore(results={RetrievalMode.VECTOR: [make_item()]})
    with pytest.raises(KnowledgeStoreContractError) as exc_info:
        await retrieve_bundle(store, _request({RetrievalMode.VECTOR}))
    _assert_closed(exc_info.value)


@pytest.mark.asyncio
async def test_evidence_with_mutated_nested_workspace_is_rejected():
    item = _evidence("chunk:1", RetrievalMode.VECTOR)
    _mutated(item.workspace, value=OTHER_WS.value)
    store = FakeStore(results={RetrievalMode.VECTOR: [item]})
    with pytest.raises(KnowledgeStoreContractError) as exc_info:
        await retrieve_bundle(store, _request({RetrievalMode.VECTOR}))
    _assert_closed(exc_info.value)


@pytest.mark.asyncio
async def test_bundle_holds_fresh_evidence_that_later_store_mutation_cannot_change():
    returned = _sourced_evidence(_source())
    bundle = await retrieve_bundle(
        FakeStore(results={RetrievalMode.VECTOR: [returned]}), _request({RetrievalMode.VECTOR})
    )
    kept = bundle.evidence[0]
    assert kept == returned and kept is not returned
    assert kept.workspace is not returned.workspace and kept.source is not returned.source
    _mutated(returned.source, key="../secrets.md")
    _mutated(returned.workspace, value=OTHER_WS.value)
    assert kept.source.key == "team/orders.md" and kept.workspace == WS


@pytest.mark.asyncio
@pytest.mark.parametrize("store_class", [MutatingStore, SilentMutatingStore])
async def test_store_mutating_its_request_is_a_contract_violation(store_class):
    request = _request({RetrievalMode.VECTOR, RetrievalMode.GRAPH}, limit=3)
    store = store_class()
    with pytest.raises(KnowledgeStoreContractError) as exc_info:
        await retrieve_bundle(store, request)
    _assert_closed(exc_info.value)
    # Only the first mode ran, and the caller's request is untouched.
    assert [mode for mode, _ in store.calls] == [RetrievalMode.VECTOR]
    assert request.workspace == WS and request.limit_per_mode == 3


@pytest.mark.asyncio
async def test_store_mutating_an_earlier_clone_cannot_alter_the_snapshot():
    store = LateMutatingStore(results={RetrievalMode.GRAPH: [_evidence("entity:n1", RetrievalMode.GRAPH)]})
    bundle = await retrieve_bundle(store, _request({RetrievalMode.VECTOR, RetrievalMode.GRAPH}, limit=3))
    assert bundle.request.workspace == WS and bundle.request.limit_per_mode == 3
    assert all(received is not bundle.request for _, received in store.calls)
    graph_request = store.calls[1][1]
    assert graph_request.workspace == WS and graph_request.limit_per_mode == 3
