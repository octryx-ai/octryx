"""Storage-neutral Knowledge contract: Workspace identity, database name,
source-object references, requests, evidence, and bundles (pure unit tests)."""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.knowledge.objects.source_object import SourceObjectRef
from app.services.knowledge.retrieval.contracts import (
    MAX_LIMIT_PER_MODE,
    MAX_QUERY_CHARS,
    Evidence,
    EvidenceKind,
    RetrievalBundle,
    RetrievalMode,
    RetrievalRequest,
)
from app.services.knowledge.retrieval.errors import (
    InvalidRetrievalRequestError,
    InvalidWorkspaceError,
    RetrievalFailureState,
    WorkspaceRequiredError,
)
from tests.services.knowledge.retrieval.knowledge_contracts_support import WS, _request, _SneakyStr, _SubWorkspace

OTHER_WS = "9c0d5d6f-7a8b-4e7b-8c21-3f2b8c1e9a4d"


# Invisible or reordering characters: C0, DEL, C1 (NEL), bidi override, zero
# width space, BOM, lone surrogate, line and paragraph separators.
UNSAFE_CHARS = ["\x00", "\x1b", "\x7f", "\x85", "\u202e", "\u2066", "\u200b", "\ufeff", "\ud800", "\u2028", "\u2029"]


def _evidence(
    evidence_id: str = "chunk:1", mode: RetrievalMode = RetrievalMode.VECTOR, workspace: str = WS
) -> Evidence:
    return Evidence(
        workspace=WorkspaceId.parse(workspace), evidence_id=evidence_id, mode=mode, kind=EvidenceKind.PASSAGE, text="t"
    )


class _LyingInt(int):
    def __le__(self, other):  # type: ignore[override]
        return True

    def __ge__(self, other):  # type: ignore[override]
        return True


class _UncheckedSource(SourceObjectRef):
    __slots__ = ()

    def __post_init__(self) -> None:
        pass


class _UncheckedEvidence(Evidence):
    __slots__ = ()

    def __post_init__(self) -> None:
        pass


class _UncheckedRequest(RetrievalRequest):
    __slots__ = ()

    def __post_init__(self) -> None:
        pass


# --- Retrieval request ------------------------------------------------------------


def test_request_normalizes_and_orders_modes():
    request = _request(query_text="  orders  ", modes=["graph", RetrievalMode.LEXICAL], workspace=WS)
    assert request.query_text == "orders"
    assert request.workspace == WorkspaceId.parse(WS)
    assert request.ordered_modes == (RetrievalMode.LEXICAL, RetrievalMode.GRAPH)
    assert request.limit_per_mode == 8


def test_request_without_workspace_is_denied():
    with pytest.raises(WorkspaceRequiredError):
        _request(workspace=None)


@pytest.mark.parametrize(
    "overrides",
    [
        {"query_text": "   "},
        {"query_text": None},
        {"query_text": "x" * (MAX_QUERY_CHARS + 1)},
        {"query_text": "drop\x00table"},
        {"modes": set()},
        {"modes": (mode for mode in ())},
        {"modes": None},
        {"modes": "vector"},
        {"modes": {"cypher"}},
        {"limit_per_mode": 0},
        {"limit_per_mode": MAX_LIMIT_PER_MODE + 1},
        {"limit_per_mode": True},
        {"limit_per_mode": "5"},
    ],
)
def test_request_bounds_are_enforced(overrides):
    with pytest.raises(InvalidRetrievalRequestError) as exc_info:
        _request(**overrides)
    assert exc_info.value.state is RetrievalFailureState.INVALID_REQUEST
    assert str(exc_info.value) == InvalidRetrievalRequestError.default_message


def test_request_accepts_a_non_empty_mode_generator():
    request = _request(modes=(mode for mode in ["graph"]))
    assert request.modes == frozenset({RetrievalMode.GRAPH})


@pytest.mark.parametrize("char", UNSAFE_CHARS)
def test_request_rejects_unsafe_characters_in_query(char):
    with pytest.raises(InvalidRetrievalRequestError):
        _request(query_text=f"orders{char}service")


@pytest.mark.parametrize(
    "overrides",
    [
        {"query_text": _SneakyStr("orders")},
        {"limit_per_mode": _LyingInt(10**6)},
        {"workspace": _SubWorkspace(uuid.UUID(WS))},
    ],
)
def test_request_requires_exact_field_types(overrides):
    with pytest.raises((InvalidRetrievalRequestError, InvalidWorkspaceError)):
        _request(**overrides)


def test_request_keeps_ordinary_line_breaks_in_query():
    assert _request(query_text="orders\tservice\r\nlatency").query_text == "orders\tservice\r\nlatency"


# --- Evidence and bundle ------------------------------------------------------------


@pytest.mark.parametrize(
    "evidence_id",
    ["#12:0", "#-1:-1", "12:0", "12:-1", "0:0", "12:0 ", "", "a b", "x" * 129, "MATCH (n) RETURN n", None],
)
def test_evidence_rejects_database_record_ids_and_unsafe_ids(evidence_id):
    with pytest.raises(InvalidRetrievalRequestError):
        _evidence(evidence_id=evidence_id)


@pytest.mark.parametrize("evidence_id", ["chunk:12:0", "entity:3f2b8c1e", "c1", "doc.v2-final"])
def test_evidence_accepts_prefixed_opaque_ids(evidence_id):
    assert _evidence(evidence_id=evidence_id).evidence_id == evidence_id


@pytest.mark.parametrize(
    "overrides",
    [
        {"text": " "},
        {"text": "x" * 8001},
        {"score": float("nan")},
        {"score": True},
        {"score": 10**400},
        {"score": "0.5"},
        {"citation": "a\nb"},
        {"source": "s3://b/k"},
        {"workspace": WS},
        {"workspace": None},
        {"mode": ["vector"]},
    ],
)
def test_evidence_fields_are_validated(overrides):
    values = {
        "workspace": WorkspaceId.parse(WS),
        "evidence_id": "chunk:1",
        "mode": RetrievalMode.VECTOR,
        "kind": EvidenceKind.PASSAGE,
        "text": "t",
    }
    values.update(overrides)
    with pytest.raises(InvalidRetrievalRequestError) as exc_info:
        Evidence(**values)
    assert str(exc_info.value) == InvalidRetrievalRequestError.default_message


@pytest.mark.parametrize("char", UNSAFE_CHARS)
def test_evidence_rejects_unsafe_characters_in_text_and_citation(char):
    with pytest.raises(InvalidRetrievalRequestError):
        Evidence(workspace=WorkspaceId.parse(WS), evidence_id="c1", mode="vector", kind="passage", text=f"a{char}b")
    with pytest.raises(InvalidRetrievalRequestError):
        Evidence(
            workspace=WorkspaceId.parse(WS),
            evidence_id="c1",
            mode="vector",
            kind="passage",
            text="t",
            citation=f"a{char}",
        )


def test_evidence_keeps_line_breaks_in_body_text_only():
    workspace = WorkspaceId.parse(WS)
    text = "line one\r\n\tline two"
    assert Evidence(workspace=workspace, evidence_id="c1", mode="vector", kind="passage", text=text).text == text
    with pytest.raises(InvalidRetrievalRequestError):
        Evidence(workspace=workspace, evidence_id="c1", mode="vector", kind="passage", text="t", citation="a\tb")


@pytest.mark.parametrize(
    "overrides",
    [
        {"workspace": _SubWorkspace(uuid.UUID(WS))},
        {"evidence_id": _SneakyStr("chunk:1")},
        {"text": _SneakyStr("t")},
        {"citation": _SneakyStr("c")},
        {"source": _UncheckedSource(bucket="BAD", key="../x")},
    ],
)
def test_evidence_requires_exact_field_and_nested_types(overrides):
    values = {"workspace": WorkspaceId.parse(WS), "evidence_id": "c1", "mode": "vector", "kind": "passage", "text": "t"}
    values.update(overrides)
    with pytest.raises(InvalidRetrievalRequestError):
        Evidence(**values)


def test_evidence_copies_and_revalidates_nested_values():
    workspace = WorkspaceId.parse(WS)
    source = SourceObjectRef(bucket="kb-docs", key="a/b.md")
    item = Evidence(workspace=workspace, evidence_id="c1", mode="vector", kind="passage", text="t", source=source)
    assert item.workspace == workspace and item.workspace is not workspace
    assert item.source == source and item.source is not source
    object.__setattr__(source, "key", "../secrets.md")
    assert item.source.key == "a/b.md"
    with pytest.raises(InvalidRetrievalRequestError):
        Evidence(workspace=workspace, evidence_id="c1", mode="vector", kind="passage", text="t", source=source)


def test_bundle_requires_exact_request_and_evidence_types():
    sneaky_evidence = _UncheckedEvidence(
        workspace=WorkspaceId.parse(WS), evidence_id="#1:0", mode=RetrievalMode.VECTOR, kind="passage", text="t"
    )
    with pytest.raises(InvalidRetrievalRequestError):
        RetrievalBundle(request=_request(), evidence=(sneaky_evidence,))
    sneaky_request = _UncheckedRequest(
        workspace=WorkspaceId.parse(WS), query_text="q", modes=frozenset({RetrievalMode.VECTOR}), limit_per_mode=10**6
    )
    with pytest.raises(InvalidRetrievalRequestError):
        RetrievalBundle(request=sneaky_request, evidence=())


def test_bundle_enforces_requested_modes_limits_and_uniqueness():
    request = _request(limit_per_mode=2)
    bundle = RetrievalBundle(request=request, evidence=[_evidence("chunk:1"), _evidence("chunk:2")])
    assert bundle.workspace == request.workspace
    assert len(bundle.for_mode(RetrievalMode.VECTOR)) == 2
    with pytest.raises(InvalidRetrievalRequestError):
        RetrievalBundle(request=request, evidence=(_evidence("a"), _evidence("b"), _evidence("c")))
    with pytest.raises(InvalidRetrievalRequestError):
        RetrievalBundle(request=request, evidence=(_evidence("a", RetrievalMode.GRAPH),))
    with pytest.raises(InvalidRetrievalRequestError):
        RetrievalBundle(request=request, evidence=(_evidence("a"), _evidence("a")))


def test_bundle_rejects_evidence_owned_by_another_workspace():
    request = _request()
    with pytest.raises(InvalidRetrievalRequestError):
        RetrievalBundle(request=request, evidence=(_evidence("a"), _evidence("b", workspace=OTHER_WS)))
