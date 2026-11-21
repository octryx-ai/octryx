"""Bind the per-turn execution snapshot so every trace of the turn records it.

``run_agent`` binds the snapshot once, right after the execution gate decided.
``persist_turn_trace`` then stamps it onto every ``TurnTrace`` of that session
without threading a new argument through the dozens of loop call sites.

The binding is a context variable holding an immutable ``session_id -> binding``
mapping. Keying by session keeps nested sub-agent turns (which run ``run_agent``
for a child session in the same task) from overwriting the parent's snapshot.
Traces persisted for a session without a bound snapshot carry none and read back
as ``missing_snapshot`` (outcome ``unknown``).

The same wrapper scopes the turn's prompt set (``services/prompt_catalog``): it is
unbound when the turn starts, bound by run preparation, and the previous binding is
restored when the generator ends, exactly like the snapshot.

Lifecycle: ``run_agent`` is wrapped by ``scoped_turn_execution_binding``. The
session's binding is removed before the turn starts (so a turn whose preparation
fails can never stamp the previous turn's decision) and, when the generator ends
for any reason (return, exception, ``aclose``/cancellation), the binding that was
active before the turn is restored, or the entry is removed if there was none.
A same-session nested run therefore never leaves its decision on the parent.

The binding also records when the turn was admitted (``bound_turn_started_at``).
That instant is the turn boundary for anything that reads the session's persisted
rows on the turn's behalf: a row created before it belongs to an earlier turn.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import AsyncGenerator, Callable, Mapping
from contextvars import ContextVar
from datetime import datetime
from types import MappingProxyType
from typing import Any

from ....services.prompt_catalog import bind_prompt_set, bound_prompt_set
from ....services.session.turn_execution_snapshot import (
    RUNTIME_OUTCOME_FINISHED,
    RUNTIME_OUTCOME_KEY,
    RUNTIME_OUTCOME_STOPPED,
    RUNTIME_STOP_REASON_KEY,
    RUNTIME_STOP_REASONS,
    TURN_EXECUTION_SNAPSHOT_KEY,
)
from ....time_utils import utc_now


class _TurnBinding:
    """Snapshot of one bound turn plus its trace sequence counter."""

    __slots__ = ("checks_recorded", "next_sequence", "snapshot", "started_at")

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = dict(snapshot)
        self.next_sequence = 0
        self.started_at = utc_now()
        self.checks_recorded = False


_BOUND_TURNS: ContextVar[Mapping[str, _TurnBinding]] = ContextVar(
    "turn_execution_bindings",
    default=MappingProxyType({}),
)


def _replace_binding(session_id: str, binding: _TurnBinding | None) -> None:
    current = dict(_BOUND_TURNS.get())
    if binding is None:
        current.pop(session_id, None)
    else:
        current[session_id] = binding
    _BOUND_TURNS.set(MappingProxyType(current))


def bind_turn_execution_snapshot(session_id: str, snapshot: dict[str, Any]) -> None:
    """Bind ``snapshot`` as the execution snapshot of the current turn of ``session_id``."""
    _replace_binding(str(session_id), _TurnBinding(snapshot))


def clear_turn_execution_snapshot(session_id: str) -> None:
    _replace_binding(str(session_id), None)


def bound_turn_execution_snapshot(session_id: str | None) -> dict[str, Any] | None:
    binding = _BOUND_TURNS.get().get(str(session_id or ""))
    return dict(binding.snapshot) if binding is not None else None


def bound_turn_started_at(session_id: str | None) -> datetime | None:
    """When the current turn of ``session_id`` was admitted, or ``None`` when no turn is bound.

    Rows the session persisted before this instant (messages, traces, tool calls)
    were produced by an earlier turn; the current turn must never present them.
    """
    binding = _BOUND_TURNS.get().get(str(session_id or ""))
    return binding.started_at if binding is not None else None


def claim_turn_checks_record(session_id: str | None) -> bool:
    """True exactly once per bound turn of ``session_id``: the turn's workflow-check result is recorded once,
    whichever path ends the turn. An unbound session (no ``run_agent`` turn) always answers True."""
    binding = _BOUND_TURNS.get().get(str(session_id or ""))
    if binding is None:
        return True
    if binding.checks_recorded:
        return False
    binding.checks_recorded = True
    return True


def scoped_turn_execution_binding(
    run: Callable[..., AsyncGenerator[Any, None]],
) -> Callable[..., AsyncGenerator[Any, None]]:
    """Scope the session's turn binding to one ``run_agent`` generator lifetime."""
    signature = inspect.signature(run)

    @functools.wraps(run)
    async def _scoped(*args: Any, **kwargs: Any) -> AsyncGenerator[Any, None]:
        session_id = str(signature.bind_partial(*args, **kwargs).arguments.get("session_id") or "")
        previous = _BOUND_TURNS.get().get(session_id)
        previous_prompt_set = bound_prompt_set()
        clear_turn_execution_snapshot(session_id)
        # The turn binds its own prompt set during preparation; a nested run restores the parent's.
        bind_prompt_set(None)
        events = run(*args, **kwargs)
        try:
            async for event in events:
                yield event
        finally:
            try:
                await events.aclose()
            finally:
                _replace_binding(session_id, previous)
                bind_prompt_set(previous_prompt_set)

    return _scoped


def stamp_turn_execution_snapshot(session_id: str | None, context_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return ``context_snapshot`` with the bound snapshot as the only trusted value.

    A caller-supplied value under the reserved key is always discarded so trace
    context can never forge an execution decision or a runtime outcome. Each
    stamped trace receives the next sequence number of its turn.
    """
    stamped = dict(context_snapshot or {})
    stamped.pop(TURN_EXECUTION_SNAPSHOT_KEY, None)
    binding = _BOUND_TURNS.get().get(str(session_id or ""))
    if binding is not None:
        snapshot = dict(binding.snapshot)
        snapshot["turn"] = {**dict(snapshot.get("turn") or {}), "sequence": binding.next_sequence}
        binding.next_sequence += 1
        stamped[TURN_EXECUTION_SNAPSHOT_KEY] = snapshot
    return stamped


def carry_turn_execution_snapshot(
    previous_context_snapshot: Any, refreshed_context_snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Keep the snapshot already persisted on a trace when its context is refreshed."""
    refreshed = dict(refreshed_context_snapshot or {})
    refreshed.pop(TURN_EXECUTION_SNAPSHOT_KEY, None)
    if isinstance(previous_context_snapshot, dict) and TURN_EXECUTION_SNAPSHOT_KEY in previous_context_snapshot:
        refreshed[TURN_EXECUTION_SNAPSHOT_KEY] = previous_context_snapshot[TURN_EXECUTION_SNAPSHOT_KEY]
    return refreshed


def mark_turn_runtime_finished(turn_trace: Any) -> None:
    """Record an accepted normal completion on the turn's final trace.

    Only call sites that accept the turn's final answer may use this; stalls,
    suppressed responses, completion blockers and salvage exits must not. A trace
    without a stamped snapshot is left untouched (it reads back as ``missing_snapshot``).
    """
    context = getattr(turn_trace, "context_snapshot_json", None)
    snapshot = context.get(TURN_EXECUTION_SNAPSHOT_KEY) if isinstance(context, dict) else None
    if not isinstance(snapshot, dict):
        return
    # Assign fresh dicts so the JSON column change is detected on flush.
    turn_trace.context_snapshot_json = {
        **context,
        TURN_EXECUTION_SNAPSHOT_KEY: {**snapshot, RUNTIME_OUTCOME_KEY: RUNTIME_OUTCOME_FINISHED},
    }


def mark_turn_runtime_stopped(turn_trace: Any, stop_reason: str) -> None:
    """Record that a runtime guard ended the turn with an explicit stop answer.

    Only the call site that persists that stop answer as the turn's final trace may
    use this, with a closed ``RUNTIME_STOP_REASONS`` code; any other value is ignored
    so the trace keeps reading ``unknown`` rather than a guessed state.
    """
    if stop_reason not in RUNTIME_STOP_REASONS:
        return
    context = getattr(turn_trace, "context_snapshot_json", None)
    snapshot = context.get(TURN_EXECUTION_SNAPSHOT_KEY) if isinstance(context, dict) else None
    if not isinstance(snapshot, dict):
        return
    turn_trace.context_snapshot_json = {
        **context,
        TURN_EXECUTION_SNAPSHOT_KEY: {
            **snapshot,
            RUNTIME_OUTCOME_KEY: RUNTIME_OUTCOME_STOPPED,
            RUNTIME_STOP_REASON_KEY: stop_reason,
        },
    }


__all__ = [
    "bind_turn_execution_snapshot",
    "bound_turn_execution_snapshot",
    "bound_turn_started_at",
    "carry_turn_execution_snapshot",
    "claim_turn_checks_record",
    "clear_turn_execution_snapshot",
    "mark_turn_runtime_finished",
    "mark_turn_runtime_stopped",
    "scoped_turn_execution_binding",
    "stamp_turn_execution_snapshot",
]
