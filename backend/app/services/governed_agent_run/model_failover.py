"""Explicit, recorded failover across the ordered aliases of one Model Policy.

When the provider behind a policy's current alias fails
*transiently*, the request moves to the next alias of the *same* policy. Nothing else
switches, and every switch is a recorded fact.

Order and admission. The aliases are tried strictly in policy order. Every alias was
admitted before the first request (``model_call.admitted_runtimes`` admits the whole
policy), and each alias chain is re-checked at dispatch as usual (the gateway driver
refuses an alias the project no longer grants with a typed ``alias_denied`` /
``data_policy_denied`` error).

Retry and failover. Each alias is one engine chain call (``_chat_with_runtime_fallback``)
with its own ``RuntimeRetryPolicy`` built for exactly that alias's targets, so the
engine's retries are unchanged and run to exhaustion first: one same-target retry for
``transient`` and ``timeout`` (a gateway alias chain has no next target, so a timeout is
retried too), and, for a request without tools, whole-chain re-cycles while every target
is ``unreachable``. Only when that call raises does this module decide. A gateway chain
keeps ``first_runtime_only`` inside one alias; the failover is the only way to reach
another alias, and it is explicit.

When a switch happens. Only when every dispatch attempt of the failed alias chain is an
error whose class is in :data:`FAILOVER_ERROR_CLASSES` *and* was classified from a typed
source (:data:`FAILOVER_CLASSIFICATION_SOURCES`: an explicit ``ProviderRuntimeError`` or
the exception type). Error text is never read. Everything else keeps its own outcome and
never switches:

* admission, policy or data-policy refusal (``alias_denied``, ``data_policy_denied``);
* capability refusal (a target skipped because it cannot serve the requested tools);
* auth or configuration errors (``permanent``, ``provider_init``);
* contract violations, malformed responses, context pressure, empty output, and any
  transient class the taxonomy reached only through its message-pattern tail;
* output schema mismatch (checked after the run, outside the chain call) and budget
  exhaustion (raised before dispatch, see below).

Budget. The platform budget policy is enforced again for the next alias's targets
before the switch; a refusal ends the run ``failed`` / ``budget_limit_exceeded`` and no
switch is recorded. Cost and tokens stay the sum over every served request, so a run's
cost cap sees all of them.

Stickiness. After a switch, later requests of the same run start at the alias that
took over; a run therefore records at most ``len(aliases) - 1`` switches.

Exhaustion. When the last alias also fails transiently the run ends ``failed`` /
:data:`MODEL_POLICY_EXHAUSTED`, and every switch made on the way stays recorded.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ...agent.core.runtime.runtime_errors import (
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
    """The admitted runtime targets of one policy alias, in resolution order."""

    alias: str
    runtimes: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ModelFailover:
    """One recorded switch: the failed alias, the alias that takes over, and why."""

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
    """Group admitted runtimes by alias, keeping the policy order of first appearance."""
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
    """The typed transient failure of a whole alias chain, or ``None`` if it must not switch.

    Decided from the engine's attempt facts only. Every dispatch attempt must be an
    ``error`` of a failover class from a typed source; one attempt that is anything else
    (an admission denial, a skipped target, a permanent or contract error, a truncated
    record) keeps the chain's own outcome. The last error attempt names the switch.
    """
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
    """Dispatch on ``chains[start]``; switch to the next alias only on a typed transient failure.

    A failure that must not switch is re-raised unchanged, so the caller classifies it
 (admission refusal or ``provider_error``). ``before_switch`` runs
    the budget check for the next alias and may raise; ``on_switch`` records the fact.
    """
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
    """The trace record of one switch: closed fields only, never provider error text."""
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
