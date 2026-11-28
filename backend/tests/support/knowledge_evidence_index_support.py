"""In-memory double of the Workspace Evidence index (``evidence_index``)."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from app.services.knowledge.embedding.catalog import EMBEDDING_SPACES
from app.services.knowledge.evidence_index import operations as ops
from app.services.knowledge.evidence_index.base import EvidenceIndexClient
from app.services.knowledge.evidence_index.errors import EvidenceIndexContractError, EvidenceIndexUnavailableError
from app.services.knowledge.evidence_index.values import checked_parameters
from app.services.knowledge.identity.workspace import WorkspaceId
from tests.knowledge_evidence_text_support import _tokens

_LEXICAL = frozenset(
    {
        ops.SEARCH_EVIDENCE_LEXICAL,
        ops.SEARCH_EVIDENCE_LEXICAL_PAIR,
        ops.SEARCH_EVIDENCE_LEXICAL_SCOPED,
        ops.SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED,
        ops.SEARCH_EVIDENCE_LEXICAL_SCOPED_VERSION,
        ops.SEARCH_EVIDENCE_LEXICAL_PAIR_SCOPED_VERSION,
    }
)
_VECTOR = frozenset(
    {ops.SEARCH_EVIDENCE_VECTOR, ops.SEARCH_EVIDENCE_VECTOR_SCOPED, ops.SEARCH_EVIDENCE_VECTOR_SCOPED_VERSION}
)
_SET_VECTOR = {ops.set_vector_operation(key): key for key in EMBEDDING_SPACES}
_READ_VECTOR = {ops.read_vector_operation(key): key for key in EMBEDDING_SPACES}


class FakeEvidenceIndex(EvidenceIndexClient):
    def __init__(self, *, unavailable: bool = False, vectors: bool = True) -> None:
        # Workspace (canonical id) -> evidence key -> record.
        self.records: dict[str, dict[str, dict[str, Any]]] = {}
        self.unavailable = unavailable
        self.vectors = vectors
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        # A test's hook ``(operation key, parameters) -> rows | None``: it may raise, answer rows
        # instead of the index, or return ``None`` to let the index answer.
        self.intercept: Callable[[str, dict[str, Any]], tuple[dict[str, Any], ...] | None] | None = None

    def __repr__(self) -> str:
        return "FakeEvidenceIndex()"

    def operation_keys(self) -> list[str]:
        return [key for key, _, _ in self.requests]

    async def vectors_available(self) -> bool:
        return self.vectors

    def workspace_records(self, workspace: str) -> dict[str, dict[str, Any]]:
        return self.records.setdefault(workspace, {})

    def evidence_keys(self, workspace: str) -> tuple[str, ...]:
        return tuple(sorted(self.records.get(workspace, {})))

    def seed_evidence(self, workspace: str, spans: dict[str, str]) -> None:
        records = self.workspace_records(workspace)
        for evidence_key, body_text in spans.items():
            revision_id, _, ordinal = evidence_key.partition(":")
            records[evidence_key] = {
                "evidence_key": evidence_key,
                "body_text": body_text,
                "revision_id": revision_id,
                "span_ordinal": int(ordinal),
                "products": [],
                "version": "",
                "acl_keys": ["public"],
            }

    async def run(
        self,
        workspace: WorkspaceId,
        operation_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        if type(workspace) is not WorkspaceId:
            raise EvidenceIndexContractError()
        try:
            spec = ops.operation(operation_key)
        except KeyError:
            raise EvidenceIndexContractError() from None
        checked = checked_parameters(spec, parameters)
        if self.unavailable:
            raise EvidenceIndexUnavailableError()
        if operation_key in (_VECTOR | set(_SET_VECTOR) | set(_READ_VECTOR)) and not self.vectors:
            raise EvidenceIndexContractError()
        project_id = workspace.canonical
        self.requests.append((operation_key, project_id, dict(checked)))
        if self.intercept is not None:
            answer = self.intercept(operation_key, dict(checked))
            if answer is not None:
                return answer
        records = self.workspace_records(project_id)
        return self._dispatch(records, operation_key, checked)

    def _dispatch(self, records: dict, key: str, params: dict) -> tuple[dict[str, Any], ...]:
        if key == ops.UPSERT_EVIDENCE_SCOPED:
            record = records.setdefault(params["evidence_key"], {})
            record.update(
                evidence_key=params["evidence_key"],
                body_text=params["body_text"],
                revision_id=params["revision_id"],
                span_ordinal=params["span_ordinal"],
                products=list(params["products"]),
                version=params["version"],
                acl_keys=list(params["acl_keys"]),
            )
            return ({"count": 1},)
        if key == ops.DELETE_EVIDENCE:
            removed = records.pop(params["evidence_key"], None)
            return ({"count": 0 if removed is None else 1},)
        if key == ops.COUNT_EVIDENCE_BY_KEY:
            return ({"total": 1 if params["evidence_key"] in records else 0},)
        if key == ops.MARK_UNMARKED_EVIDENCE:
            unmarked = [record for record in records.values() if record.get("acl_keys") is None]
            for record in unmarked[: params["cap"]]:
                record["acl_keys"] = list(params["acl_keys"])
            return ({"count": min(len(unmarked), params["cap"])},)
        if key in _SET_VECTOR:
            # No vector-only ghost rows: a vector is only written for a span the index holds.
            record = records.get(params["evidence_key"])
            if record is not None:
                record.setdefault("vectors", {})[_SET_VECTOR[key]] = list(params["embedding"])
            return ({"count": 0 if record is None else 1},)
        if key in _READ_VECTOR:
            record = records.get(params["evidence_key"])
            vector = (record or {}).get("vectors", {}).get(_READ_VECTOR[key])
            return ({"vector": list(vector)},) if vector is not None else ()
        if key in _VECTOR:
            return self._nearest(records, params)
        if key in _LEXICAL:
            return self._search(records, params)
        raise EvidenceIndexContractError()  # pragma: no cover - every registered key is dispatched

    @staticmethod
    def _in_scope(record: dict, params: dict) -> bool:
        if not set(params["principals"]) & set(record.get("acl_keys") or []):
            return False
        if "products" in params and not set(params["products"]) & set(record.get("products") or []):
            return False
        return "version" not in params or record.get("version") == params["version"]

    def _search(self, records: dict, params: dict) -> tuple[dict[str, Any], ...]:
        terms = [params["term"]] if "term" in params else [params["term_a"], params["term_b"]]
        predicates = [_tokens(term) for term in terms]
        matched = [
            {"evidence_key": record["evidence_key"], "body_text": record["body_text"]}
            for _, record in sorted(records.items())
            if all(predicate & _tokens(record["body_text"]) for predicate in predicates)
            and self._in_scope(record, params)
        ]
        return tuple(matched[: params["cap"]])

    def _nearest(self, records: dict, params: dict) -> tuple[dict[str, Any], ...]:
        space = EMBEDDING_SPACES.get(params["space"])
        query = params["vector"]
        if space is None or len(query) != space.dimensions:
            raise EvidenceIndexContractError()

        def distance(vector: list[float]) -> float:
            dot = sum(a * b for a, b in zip(query, vector, strict=True))
            norm = math.sqrt(sum(a * a for a in query)) * math.sqrt(sum(b * b for b in vector))
            return 1.0 - dot / norm if norm else 1.0

        scored = sorted(
            (distance(record["vectors"][space.key]), key, record["body_text"])
            for key, record in records.items()
            if space.key in record.get("vectors", {}) and self._in_scope(record, params)
        )
        return tuple(
            {"evidence_key": key, "body_text": text, "distance": d} for d, key, text in scored[: params["k"]]
        )


__all__ = ["FakeEvidenceIndex"]
