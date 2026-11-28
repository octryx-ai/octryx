"""Explicit, recorded failover across the ordered aliases of one Model Policy."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.agent.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
    CLASSIFICATION_SOURCE_EXPLICIT,
    RUNTIME_ERROR_TIMEOUT,
    RUNTIME_ERROR_TRANSIENT,
    RUNTIME_ERROR_UNREACHABLE,
)

from ..model_policy.entries import MAX_ENTRIES
from .provider_failure import failure_detail
from .refusals import failed

logger = logging.getLogger(__name__)

#: The closed set of runtime error classes that move a request to the next policy alias.
FAILOVER_ERROR_CLASSES: frozenset[str] = frozenset(
    {RUNTIME_ERROR_TIMEOUT, RUNTIME_ERROR_UNREACHABLE, RUNTIME_ERROR_TRANSIENT}
)
#: Only a typed classification may switch; the taxonomy's message-pattern tail never does.
FAILOVER_CLASSIFICATION_SOURCES: frozenset[str] = frozenset(
    {CLASSIFICATION_SOURCE_EXPLICIT, CLASSIFICATION_SOURCE_EXCEPTION_TYPE}
)
MODEL_POLICY_EXHAUSTED = "model_policy_exhausted"
FAILOVER_FACT_KEYS: frozenset[str] = frozenset({"from_alias", "to_alias", "error_class", "error_class_source"})
#: A policy has at most ``MAX_ENTRIES`` aliases, so a run records at most one fewer switches.
MAX_FAILOVER_FACTS = MAX_ENTRIES - 1

# Engine bookkeeping records that are not dispatch attempts: the pause between
# whole-chain re-cycles, and ``first_runtime_only`` declining a second target of one alias.
_BOOKKEEPING_STATUSES = frozenset({"retry_wait", "fallback_denied"})


@dataclass(frozen=True, slots=True)
class AliasChain:
    alias: str
    runtimes: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ModelFailover:
    from_alias: str
    to_alias: str
    error_class: str
    error_class_source: str

    def as_fact(self) -> dict[str, str]:
        return {
            "from_alias": self.from_alias,
            "to_alias": self.to_alias,
            "error_class": self.error_class,
            "error_class_source": self.error_class_source,
        }


@dataclass(frozen=True, slots=True)
class TransientFailure:
    error_class: str
    error_class_source: str


def alias_chains(runtimes: Sequence[dict[str, Any]]) -> tuple[AliasChain, ...]:
    order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for runtime in runtimes:
        alias = str(runtime.get("model") or "").strip()
        if alias not in grouped:
            order.append(alias)
            grouped[alias] = []
        grouped[alias].append(runtime)
    return tuple(AliasChain(alias, tuple(grouped[alias])) for alias in order)


def transient_failure(runtime_attempts: Any) -> TransientFailure | None:
    if not isinstance(runtime_attempts, list):
        return None
    decisive: TransientFailure | None = None
    for attempt in runtime_attempts:
        if not isinstance(attempt, dict):
            return None
        if attempt.get("status") in _BOOKKEEPING_STATUSES:
            continue
        error_class = attempt.get("error_class")
        source = attempt.get("error_class_source")
        if (
            attempt.get("status") != "error"
            or error_class not in FAILOVER_ERROR_CLASSES
            or source not in FAILOVER_CLASSIFICATION_SOURCES
        ):
            return None
        decisive = TransientFailure(str(error_class), str(source))
    return decisive


Dispatch = Callable[[AliasChain], Awaitable[tuple[dict[str, Any], dict[str, Any]]]]
BeforeSwitch = Callable[[AliasChain], Awaitable[None]]
OnSwitch = Callable[[ModelFailover], None]


async def dispatch_with_failover(
    chains: Sequence[AliasChain],
    *,
    start: int,
    dispatch: Dispatch,
    before_switch: BeforeSwitch,
    on_switch: OnSwitch,
) -> tuple[dict[str, Any], dict[str, Any]]:
    index = start
    while True:
        chain = chains[index]
        try:
            return await dispatch(chain)
        except Exception as exc:
            failure = transient_failure(getattr(exc, "runtime_attempts", None))
            if failure is None:
                raise
            if index + 1 >= len(chains):
                detail = failure_detail(getattr(exc, "runtime_attempts", None))
                raise failed(MODEL_POLICY_EXHAUSTED, detail=detail) from None
        following = chains[index + 1]
        await before_switch(following)
        on_switch(ModelFailover(chain.alias, following.alias, failure.error_class, failure.error_class_source))
        index += 1


def log_failover(*, attempt_id: str, dispatch_owner: str, switch: ModelFailover) -> None:
    logger.info(
        "governed_agent_run.model_failover",
        extra={"attempt_id": attempt_id, "dispatch_owner": dispatch_owner, **switch.as_fact()},
    )


__all__ = [
    "FAILOVER_CLASSIFICATION_SOURCES",
    "FAILOVER_ERROR_CLASSES",
    "FAILOVER_FACT_KEYS",
    "MAX_FAILOVER_FACTS",
    "MODEL_POLICY_EXHAUSTED",
    "AliasChain",
    "ModelFailover",
    "TransientFailure",
    "alias_chains",
    "dispatch_with_failover",
    "log_failover",
    "transient_failure",
]
