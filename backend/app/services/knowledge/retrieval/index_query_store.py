"""``KnowledgeQueryStore`` served by the Workspace Evidence index (``evidence_index``).

Lexical and vector retrieval. Vector search embeds the query in the Instance's embedding space and
asks the index for that space's nearest spans, so it only ever compares vectors of one space.
Without a configured space, and for graph, the mode raises the typed
:class:`KnowledgeIndexUnavailableError`, so a request that asks for it fails the whole request at the
facade instead of silently returning lexical hits that look like a complete answer.

Bounded plan retrieval. ``lexical_recall`` builds a fetch plan from the query terms: tier 1 is one
single-term fetch per term form, tier 2 (run after it) one conjunctive fetch per pair of terms whose
tier-1 fetches filled their cap, at most ``MAX_FETCHES`` in total. Every fetch is a registry
operation carrying the same server-owned ``LIMIT :cap`` (``min(limit_per_mode * 4, 64)``), so
neither the number of fetches nor the size of any fetch depends on how many records match. Ranking
runs over the deduplicated union of those bounded results only (``lexical_ranking``). No relevance
``score`` is published for lexical hits; it orders the results and stays internal.

The bound is enforced on this side too. A fetch that answers with more rows than its own cap is a
contract violation rather than a larger candidate set.

Fail-closed and whole-request. Every fetch of the plan must succeed; the first failure **in plan
order** becomes the typed store error, so a partially answered plan can never be mistaken for a
complete result, and the raised error does not depend on which fetch lost the race. That holds for
all three ways one fetch can fail — the index, a response over its own cap, and a malformed row.
Errors are raised outside every handler, so no index error is chained as context.

The index is never trusted as the source of truth for lineage. The adapter returns the evidence key
and text only; the citation and the source revision are re-resolved from the ledger by the
retrieval service. Query text is only ever passed as bound parameter values.
"""

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
    """Translate one index failure into this boundary's typed state.

    ``None`` means the failure is not this boundary's: it is re-raised unchanged
    rather than flattened into a retrieval state.
    """
    if isinstance(error, EvidenceIndexContractError):
        # A refusal by the closed registry means the call does not match the contract.
        return KnowledgeStoreContractError()
    if isinstance(error, EvidenceIndexError):
        # The index cannot answer right now.
        return KnowledgeIndexUnavailableError(_LEXICAL)
    return None


class EvidenceIndexQueryStore:
    """Query store over one deployment's Workspace Evidence index.

    One store serves every Workspace: the Workspace of the validated request
    selects the rows, so no caller can direct a search at another Workspace.

    Precondition: the request's Workspace has been projected. The retrieval
    service checks that against its ledger before building a request, so an
    un-projected Workspace never reaches here.
    """

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
        """Term retrieval served by the Workspace's full-text index."""
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
        """Nearest spans in the Instance's embedding space; ``score`` is the cosine similarity.

        The caller admits the Workspace for a remote space before the request reaches here,
        because the query text is what leaves the process.
        """
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
        """Explicitly unavailable: this slice projects no entities or relations."""
        raise KnowledgeIndexUnavailableError(RetrievalMode.GRAPH.value)

    async def _collect(
        self,
        client: EvidenceIndexClient,
        request: RetrievalRequest,
        plan: tuple[LexicalFetch, ...],
        cap: int,
    ) -> tuple[dict[str, str], list[frozenset[str]]]:
        """Run the whole plan and merge it, or fail the request; also each fetch's matched keys.

        The fetches are dispatched together (the client's own connection limit is
        the concurrency bound) because they are independent bounded reads of one
        Workspace's index. ``return_exceptions`` keeps the results positional, so
        the failure that is reported is the first one in plan order rather than the
        first one to arrive, and nothing is raised from inside a handler.

        Every check therefore only *records* a failure and keeps walking the plan;
        this loop is the one place that decides which failure the request reports.
        """
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
        """Keep rows that carry both projected fields, stripped, deduplicated by key.

        Answers whether every row was well-formed instead of raising, so the caller
        can keep the earliest plan-order failure. A malformed row ends the merge for
        this fetch; the candidates merged so far are discarded with the request.

        One span can be returned by several fetches of the plan; the first spelling
        wins, which is the same text either way because the key identifies the record.
        """
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
