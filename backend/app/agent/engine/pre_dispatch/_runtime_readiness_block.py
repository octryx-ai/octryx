"""Stop a turn before provider initialization when no runtime target is executable."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ....services.session.runtime_readiness_gate import (
    RUNTIME_READINESS_GATE_TRACE_PROVIDER,
    resolve_runtime_readiness,
)

logger = logging.getLogger(__name__)


async def block_turn_without_ready_runtime(
    *,
    db: Any,
    session_id: str,
    runtimes: list[dict[str, Any]] | None,
    runtime_target_id: str | None,
    resolve_runtimes_func: Callable[..., Awaitable[list[dict[str, Any]]]],
    persist_traced_assistant_message_func: Callable[..., Awaitable[Any]],
    trace_context_snapshot: dict[str, Any] | None = None,
) -> str | None:
    """Return the persisted ``needs_configuration`` message, or ``None`` to run.

    ``trace_context_snapshot`` carries the run's frozen execution profile so the
    blocked turn's trace records the profile it was blocked under.
    """
    decision = await resolve_runtime_readiness(
        db,
        runtimes=runtimes,
        runtime_target_id=runtime_target_id,
        resolve_runtimes_func=resolve_runtimes_func,
    )
    if decision.allowed:
        return None
    logger.info(
        "agent.run.blocked_by_runtime_readiness",
        extra={
            "session_id": session_id,
            "status": decision.status,
            "skipped_target_count": len(decision.skipped_targets),
        },
    )
    # Mirrors the execution-gate block: the loop never runs, so the explanation
    # and its secret-free readiness reasons are persisted here. The blocked turn
    # did not advance the conversation, so the structured thread context keeps
    # describing the last real turn (a later model must not continue from this notice).
    await persist_traced_assistant_message_func(
        db=db,
        session_id=session_id,
        content=decision.user_message,
        provider=RUNTIME_READINESS_GATE_TRACE_PROVIDER,
        model="",
        input_messages=[],
        context_snapshot=dict(trace_context_snapshot or {}),
        raw_output=decision.trace_output(),
        update_thread_context=False,
    )
    return decision.user_message


__all__ = ["block_turn_without_ready_runtime"]
