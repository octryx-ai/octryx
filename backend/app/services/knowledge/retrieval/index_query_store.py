"""``KnowledgeQueryStore`` served by the Workspace Evidence index (``evidence_index``). An unconfigured mode fails the
whole request, never falls back to lexical."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from ..embedding.port import EmbeddingError, EmbeddingPurpose, EmbeddingRuntime
from ..evidence_index.base import EvidenceIndexClient
from ..evidence_index.errors import EvidenceIndexContractError, EvidenceIndexError
from ..text_safety import remove_unsafe_chars
from .contracts import Evidence, EvidenceKind, RetrievalMode, RetrievalRequest, is_valid_evidence_id
from .errors import KnowledgeIndexUnavailableError, KnowledgeStoreContractError, KnowledgeStoreNotConfiguredError
from .lexical_ranking import fetch_evidence, rank_candidates
from .lexical_recall import LexicalFetch, candidate_cap, fetch_plan, pair_plan
from .lexical_terms import query_terms
from .stage_timing import timed_stage
from .vector_operation import vector_operation as _vector_operation

logger = logging.getLogger(__name__)

_LEXICAL = RetrievalMode.LEXICAL.value
_VECTOR = RetrievalMode.VECTOR.value


def _mapped_failure(error: BaseException) -> Exception | None:
    # ``None``: not this boundary's failure; it is re-raised unchanged, never flattened into a retrieval state.
    if isinstance(error, EvidenceIndexContractError):
        # A refusal by the closed registry means the call does not match the contract.
        return KnowledgeStoreContractError()
    if isinstance(error, EvidenceIndexError):
        # The index cannot answer right now.
        return KnowledgeIndexUnavailableError(_LEXICAL)
    return None


class EvidenceIndexQueryStore:
    # The validated request's Workspace selects the rows, so no caller can search another Workspace.
    def __init__(self, client: EvidenceIndexClient | None, *, embedding: EmbeddingRuntime | None = None) -> None:
        if client is not None and not isinstance(client, EvidenceIndexClient):
            raise KnowledgeStoreNotConfiguredError()
        if embedding is not None and type(embedding) is not EmbeddingRuntime:
            raise KnowledgeStoreNotConfiguredError()
        self._client = client
        self._embedding = embedding

    def __repr__(self) -> str:
        return f"EvidenceIndexQueryStore(configured={self._client is not None})"

    async def search_lexical(self, request: RetrievalRequest) -> Sequence[Evidence]:
        if type(request) is not RetrievalRequest:
            raise KnowledgeStoreContractError()
        if self._client is None:
            raise KnowledgeStoreNotConfiguredError()
        # Stripped, not rejected: the contract already refused unsafe query text,
        # and the parameter values must stay inside the transport's alphabet.
        query_text = remove_unsafe_chars(request.query_text, allow_line_breaks=False).strip()
        singles = fetch_plan(query_text, request.products, request.version, request.acl_keys)
        if not singles:
            return ()
        cap = candidate_cap(request.limit_per_mode)

        # Tier 1, then tier 2 only for the terms whose tier-1 fetches filled their cap.
        candidates, matched = await self._collect(self._client, request, singles, cap)
        pairs = pair_plan(singles, [len(found) >= cap for found in matched])
        if pairs:
            more, _ = await self._collect(self._client, request, pairs, cap)
            for evidence_key, body_text in more.items():
                candidates.setdefault(evidence_key, body_text)
        evidence = fetch_evidence([fetch.serves for fetch in singles], matched, cap)
        ranked = rank_candidates(candidates, query_terms(query_text), evidence, cap)
        return tuple(
            Evidence(
                workspace=request.workspace,
                evidence_id=evidence_key,
                mode=RetrievalMode.LEXICAL,
                kind=EvidenceKind.PASSAGE,
                text=body_text,
            )
            for evidence_key, body_text in ranked[: request.limit_per_mode]
        )

    async def search_vector(self, request: RetrievalRequest) -> Sequence[Evidence]:
        # The caller admits the Workspace for a remote space first: the query text leaves the process.
        if type(request) is not RetrievalRequest:
            raise KnowledgeStoreContractError()
        if self._client is None:
            raise KnowledgeStoreNotConfiguredError()
        if self._embedding is None:
            raise KnowledgeIndexUnavailableError(_VECTOR)
        query_text = remove_unsafe_chars(request.query_text, allow_line_breaks=False).strip()
        if not query_text:
            return ()
        space = self._embedding.space
        failure: Exception | None = None
        try:
            with timed_stage("embed"):
                vector = (await self._embedding.embedder.embed([query_text], EmbeddingPurpose.QUERY))[0]
            operation, parameters = _vector_operation(request, space.key, vector)
            # The index query alone, so "vector" (which includes the embedding) can be told apart from it.
            with timed_stage("vector_query"):
                rows = await self._client.run(request.workspace, operation, parameters)
        except EmbeddingError:
            failure = KnowledgeIndexUnavailableError(_VECTOR)
        except EvidenceIndexContractError:
            # As for lexical: a refusal by the closed registry is a contract mismatch.
            failure = KnowledgeStoreContractError()
        except EvidenceIndexError:
            failure = KnowledgeIndexUnavailableError(_VECTOR)
        # Raised outside the handlers so no dependency error is chained as context.
        if failure is not None:
            raise failure
        if len(rows) > request.limit_per_mode:
            raise KnowledgeStoreContractError()
        return tuple(self._vector_evidence(request, row) for row in rows)

    @staticmethod
    def _vector_evidence(request: RetrievalRequest, row: dict[str, object]) -> Evidence:
        key, text, distance = row.get("evidence_key"), row.get("body_text"), row.get("distance")
        if not is_valid_evidence_id(key) or type(text) is not str or type(distance) not in (int, float):
            raise KnowledgeStoreContractError()
        return Evidence(
            workspace=request.workspace,
            evidence_id=key,
            mode=RetrievalMode.VECTOR,
            kind=EvidenceKind.PASSAGE,
            text=text,
            # COSINE distance is 1 - similarity; clamp float noise into [0, 1].
            score=min(1.0, max(0.0, 1.0 - float(distance))),
        )

    async def search_graph(self, request: RetrievalRequest) -> Sequence[Evidence]:
        raise KnowledgeIndexUnavailableError(RetrievalMode.GRAPH.value)

    async def _collect(
        self,
        client: EvidenceIndexClient,
        request: RetrievalRequest,
        plan: tuple[LexicalFetch, ...],
        cap: int,
    ) -> tuple[dict[str, str], list[frozenset[str]]]:
        # ``return_exceptions`` keeps results positional, so the reported failure is the first in plan order.
        results = await asyncio.gather(
            *(client.run(request.workspace, fetch.operation, fetch.parameters(cap)) for fetch in plan),
            return_exceptions=True,
        )
        failure: Exception | None = None
        candidates: dict[str, str] = {}
        matched: list[frozenset[str]] = []
        for rows in results:
            if isinstance(rows, BaseException):
                mapped = _mapped_failure(rows)
                if mapped is None:
                    raise rows
                failure = failure or mapped
                matched.append(frozenset())
                continue
            matched.append(frozenset(str(row.get("evidence_key")) for row in rows if isinstance(row, dict)))
            if len(rows) > cap:
                # The server owns the bound; more rows than the cap means it was
                # not applied, which is a contract violation, not extra recall.
                failure = failure or KnowledgeStoreContractError()
                continue
            if not self._merge(candidates, rows):
                # A malformed row is this fetch's contract violation, recorded in
                # plan order like any other failure. Raising it here would let a
                # later fetch's bad row override an earlier fetch's mapped failure.
                failure = failure or KnowledgeStoreContractError()
        if failure is not None:
            logger.warning("Knowledge lexical retrieval failed: workspace=%s", request.workspace.canonical)
            raise failure
        return candidates, matched

    def _merge(self, candidates: dict[str, str], rows: tuple[dict[str, object], ...]) -> bool:
        for row in rows:
            evidence_key = row.get("evidence_key")
            body_text = row.get("body_text")
            if type(evidence_key) is not str or type(body_text) is not str:
                return False
            text = remove_unsafe_chars(body_text, allow_line_breaks=True).strip()
            if not text:
                continue
            candidates.setdefault(evidence_key, text)
        return True
