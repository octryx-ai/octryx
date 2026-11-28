"""Knowledge retrieval facade: one validated request in, one bounded bundle out. An unavailable index fails the whole
request; store output is re-validated."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import TypeVar, cast

from .contracts import Evidence, RetrievalBundle, RetrievalMode, RetrievalRequest
from .errors import (
    InvalidRetrievalRequestError,
    InvalidWorkspaceError,
    KnowledgeIndexUnavailableError,
    KnowledgeRetrievalError,
    KnowledgeStoreContractError,
    KnowledgeStoreNotConfiguredError,
    WorkspaceRequiredError,
    WorkspaceScopeError,
)
from .query_store import KnowledgeQueryStore

logger = logging.getLogger(__name__)

_Contract = TypeVar("_Contract", RetrievalRequest, Evidence)

_SearchMethod = Callable[[RetrievalRequest], Awaitable[Sequence[Evidence]]]
_METHOD_NAMES = {
    RetrievalMode.LEXICAL: "search_lexical",
    RetrievalMode.VECTOR: "search_vector",
    RetrievalMode.GRAPH: "search_graph",
}


def _store_methods(store: object) -> dict[RetrievalMode, _SearchMethod]:
    methods: dict[RetrievalMode, _SearchMethod] = {}
    for mode, name in _METHOD_NAMES.items():
        try:
            method = getattr(store, name, None)
        except Exception:  # noqa: BLE001 - a raising attribute is a misconfigured store
            method = None
        if method is None or not inspect.iscoroutinefunction(method):
            raise KnowledgeStoreNotConfiguredError()
        methods[mode] = method
    return methods


def _revalidated(value: object, contract: type[_Contract]) -> _Contract:
    if type(value) is not contract:
        raise InvalidRetrievalRequestError()
    return replace(cast(_Contract, value))


def _request_snapshot(request: object) -> RetrievalRequest:
    failure: KnowledgeRetrievalError
    try:
        return _revalidated(request, RetrievalRequest)
    except WorkspaceRequiredError:
        failure = WorkspaceRequiredError()
    except WorkspaceScopeError:
        failure = InvalidWorkspaceError()
    except Exception:  # noqa: BLE001 - any other defect is an invalid request
        failure = InvalidRetrievalRequestError()
    raise failure


def _checked_results(results: object, snapshot: RetrievalRequest, mode: RetrievalMode) -> tuple[Evidence, ...]:
    if isinstance(results, str | bytes) or not isinstance(results, Sequence):
        raise KnowledgeStoreContractError()
    items = tuple(results)
    if len(items) > snapshot.limit_per_mode:
        raise KnowledgeStoreContractError()
    # Checks run on the rebuilt objects, never on what the store returned.
    evidence = tuple(_revalidated(item, Evidence) for item in items)
    for item in evidence:
        if item.mode is not mode or item.workspace != snapshot.workspace:
            raise KnowledgeStoreContractError()
    return evidence


async def _search(method: _SearchMethod, snapshot: RetrievalRequest, mode: RetrievalMode) -> tuple[Evidence, ...]:
    failure: KnowledgeRetrievalError
    try:
        clone = replace(snapshot)
        evidence = _checked_results(await method(clone), snapshot, mode)
        # A store must treat its request as read-only; any change is a violation.
        if _revalidated(clone, RetrievalRequest) != snapshot:
            raise KnowledgeStoreContractError()
        return evidence
    except KnowledgeIndexUnavailableError:
        # Re-issued for the requested mode: a store cannot report another mode.
        failure = KnowledgeIndexUnavailableError(mode.value)
    except Exception:  # noqa: BLE001 - closed boundary: nothing from a store escapes raw
        failure = KnowledgeStoreContractError()
    # Raised outside the handler so no store exception is chained as context.
    logger.warning("Knowledge retrieval failed: state=%s mode=%s", failure.state.value, mode.value)
    raise failure


async def retrieve_bundle(store: KnowledgeQueryStore | None, request: RetrievalRequest) -> RetrievalBundle:
    snapshot = _request_snapshot(request)
    if store is None:
        raise KnowledgeStoreNotConfiguredError()
    methods = _store_methods(store)

    evidence: list[Evidence] = []
    for mode in snapshot.ordered_modes:
        evidence.extend(await _search(methods[mode], snapshot, mode))
    try:
        return RetrievalBundle(request=snapshot, evidence=tuple(evidence))
    except InvalidRetrievalRequestError:
        # Only reachable through store output (e.g. duplicate evidence ids).
        failure = KnowledgeStoreContractError()
    raise failure
