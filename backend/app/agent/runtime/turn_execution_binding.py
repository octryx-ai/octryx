"""Bind the per-turn execution snapshot so every trace of the turn records it."""

from __future__ import annotations

import functools
import inspect
from collections.abc import AsyncGenerator, Callable, Mapping
from contextvars import ContextVar
from datetime import datetime
from types import MappingProxyType
from typing import Any

from app.services.prompt_catalog import bind_prompt_set, bound_prompt_set
from app.services.session.turn_execution_snapshot import (
    RUNTIME_OUTCOME_FINISHED,
    RUNTIME_OUTCOME_KEY,
    RUNTIME_OUTCOME_STOPPED,
    RUNTIME_STOP_REASON_KEY,
    RUNTIME_STOP_REASONS,
    TURN_EXECUTION_SNAPSHOT_KEY,
)
from app.time_utils import utc_now


class _TurnBinding:
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
    _replace_binding(str(session_id), _TurnBinding(snapshot))


def clear_turn_execution_snapshot(session_id: str) -> None:
    _replace_binding(str(session_id), None)


def bound_turn_execution_snapshot(session_id: str | None) -> dict[str, Any] | None:
    binding = _BOUND_TURNS.get().get(str(session_id or ""))
    return dict(binding.snapshot) if binding is not None else None


def bound_turn_started_at(session_id: str | None) -> datetime | None:
    binding = _BOUND_TURNS.get().get(str(session_id or ""))
    return binding.started_at if binding is not None else None


def claim_turn_checks_record(session_id: str | None) -> bool:
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
    refreshed = dict(refreshed_context_snapshot or {})
    refreshed.pop(TURN_EXECUTION_SNAPSHOT_KEY, None)
    if isinstance(previous_context_snapshot, dict) and TURN_EXECUTION_SNAPSHOT_KEY in previous_context_snapshot:
        refreshed[TURN_EXECUTION_SNAPSHOT_KEY] = previous_context_snapshot[TURN_EXECUTION_SNAPSHOT_KEY]
    return refreshed


def mark_turn_runtime_finished(turn_trace: Any) -> None:
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
