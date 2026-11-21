"""Knowledge retrieval facade and ``KnowledgeQueryStore`` boundary (pure tests)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from app.services.knowledge.retrieval.contracts import EvidenceKind, RetrievalMode
from app.services.knowledge.retrieval.errors import (
    InvalidRetrievalRequestError,
    KnowledgeIndexUnavailableError,
    KnowledgeStoreContractError,
    KnowledgeStoreNotConfiguredError,
    WorkspaceRequiredError,
)
from app.services.knowledge.retrieval.facade import retrieve_bundle
from app.services.knowledge.retrieval.query_store import KnowledgeQueryStore
from tests.knowledge_retrieval_facade_support import OTHER_WS, WS, FakeStore, _assert_closed, _evidence, _request

SECRET = "SELECT token FROM credentials WHERE id = 'orders service'"


PACKAGE_DIR = Path(__file__).resolve().parents[1] / "app" / "services" / "knowledge"


class SyncStore:
    def search_lexical(self, request):
        return []

    def search_vector(self, request):
        return []

    def search_graph(self, request):
        return []


class AttributeStore:
    search_lexical = search_vector = search_graph = "not callable"


class PartialStore(FakeStore):
    search_graph = None  # type: ignore[assignment]


class RaisingAttributeStore(FakeStore):
    @property
    def search_graph(self):  # type: ignore[override]
        raise RuntimeError(SECRET)


@pytest.mark.asyncio
async def test_bundle_collects_modes_in_deterministic_order():
    store = FakeStore(
        results={
            RetrievalMode.GRAPH: [_evidence("entity:n1", RetrievalMode.GRAPH, EvidenceKind.ENTITY)],
            RetrievalMode.VECTOR: [_evidence("chunk:c1", RetrievalMode.VECTOR)],
        }
    )
    request = _request({RetrievalMode.GRAPH, RetrievalMode.VECTOR})
    bundle = await retrieve_bundle(store, request)
    assert [mode for mode, _ in store.calls] == [RetrievalMode.VECTOR, RetrievalMode.GRAPH]
    # Each store call gets its own validated clone, never the caller's object.
    received = [clone for _, clone in store.calls]
    assert all(clone == request and clone is not request for clone in received)
    assert received[0] is not received[1] and received[0].workspace is not received[1].workspace
    assert bundle.request == request and bundle.request is not request
    assert [item.evidence_id for item in bundle.evidence] == ["chunk:c1", "entity:n1"]
    assert bundle.workspace == WS


@pytest.mark.asyncio
async def test_unrequested_modes_are_never_called():
    store = FakeStore()
    await retrieve_bundle(store, _request({RetrievalMode.LEXICAL}))
    assert [mode for mode, _ in store.calls] == [RetrievalMode.LEXICAL]


@pytest.mark.asyncio
async def test_missing_store_needs_configuration():
    with pytest.raises(KnowledgeStoreNotConfiguredError):
        await retrieve_bundle(None, _request({RetrievalMode.VECTOR}))


@pytest.mark.asyncio
@pytest.mark.parametrize("store", [object(), SyncStore(), AttributeStore(), PartialStore(), RaisingAttributeStore()])
async def test_store_without_three_async_methods_needs_configuration(store):
    with pytest.raises(KnowledgeStoreNotConfiguredError) as exc_info:
        await retrieve_bundle(store, _request({RetrievalMode.VECTOR}))  # type: ignore[arg-type]
    _assert_closed(exc_info.value)


@pytest.mark.asyncio
async def test_unavailable_index_fails_the_whole_request():
    store = FakeStore(
        results={RetrievalMode.LEXICAL: [_evidence("chunk:c1", RetrievalMode.LEXICAL)]},
        unavailable=frozenset({RetrievalMode.GRAPH}),
    )
    with pytest.raises(KnowledgeIndexUnavailableError) as exc_info:
        await retrieve_bundle(store, _request({RetrievalMode.LEXICAL, RetrievalMode.GRAPH}))
    assert exc_info.value.mode == "graph"
    _assert_closed(exc_info.value)


@pytest.mark.asyncio
async def test_unavailable_error_is_reissued_for_the_requested_mode():
    store = FakeStore(raises={RetrievalMode.VECTOR: KnowledgeIndexUnavailableError("graph")})
    with pytest.raises(KnowledgeIndexUnavailableError) as exc_info:
        await retrieve_bundle(store, _request({RetrievalMode.VECTOR}))
    assert exc_info.value.mode == "vector"
    _assert_closed(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError(SECRET),
        TypeError(SECRET),
        ValueError(SECRET),
        KeyError(SECRET),
        OperationalError(SECRET, {"token": "orders service"}, Exception(SECRET)),
        InvalidRetrievalRequestError(),
        WorkspaceRequiredError(),
        KnowledgeStoreNotConfiguredError(),
    ],
)
async def test_store_exceptions_never_escape_raw(error):
    store = FakeStore(raises={RetrievalMode.VECTOR: error})
    with pytest.raises(KnowledgeStoreContractError) as exc_info:
        await retrieve_bundle(store, _request({RetrievalMode.VECTOR}))
    _assert_closed(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results",
    [
        [_evidence(f"chunk:{i}", RetrievalMode.VECTOR) for i in range(4)],  # over the limit
        [_evidence("entity:n1", RetrievalMode.GRAPH)],  # wrong mode
        [{"id": "chunk:1", "text": "raw row"}],  # not product evidence
        "chunk:1",  # not a sequence of evidence
        [_evidence("chunk:1", RetrievalMode.VECTOR), _evidence("chunk:1", RetrievalMode.VECTOR)],  # duplicates
        [_evidence("chunk:1", RetrievalMode.VECTOR, workspace=OTHER_WS)],  # foreign-owned evidence
        None,  # no result at all
    ],
)
async def test_store_output_violating_the_contract_is_rejected(results):
    store = FakeStore(results={RetrievalMode.VECTOR: results})
    with pytest.raises(KnowledgeStoreContractError) as exc_info:
        await retrieve_bundle(store, _request({RetrievalMode.VECTOR}))
    _assert_closed(exc_info.value)


def test_fake_store_satisfies_protocol():
    assert isinstance(FakeStore(), KnowledgeQueryStore)


def test_contract_package_has_no_storage_or_orm_imports():
    forbidden = (
        "sqlalchemy",
        "app.",
        "neo4j",
        "boto3",
        "botocore",
        "graphiti",
        "asyncpg",
        "psycopg",
        "aiosqlite",
    )
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [("." * node.level) + (node.module or "")]
            else:
                continue
            for name in names:
                assert not name.startswith("..") and not name.startswith(forbidden), f"{path.name} imports {name}"
