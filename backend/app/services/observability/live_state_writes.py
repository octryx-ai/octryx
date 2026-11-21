"""The handlers of the writes the ORM hook hands to the live register (:mod:`live_state`): each returns what to
apply on commit."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import inspect

from .live_state import (
    APPROVALS,
    FINISHED_RUNS,
    JOB_USAGE_KEYS,
    JOBS,
    RUN_OF_SESSION,
    RUN_TOKENS,
    RUNS,
    SESSIONS,
    TOKEN_TYPES,
    held,
)


def run_written(row: Any) -> Callable[[], None] | None:
    run_id = held(row, "id")
    if not run_id:
        return None
    item_id = held(row, "work_item_id")
    created = held(row, "created_at")
    fields = {
        "ticket": held(row, "ticket_key"), "workflow": held(row, "workflow_key"),
        "workspace": held(row, "project_id"), "phase": held(row, "current_node_id"),
        "status": held(row, "status"), "waiting_kind": held(row, "waiting_kind") or "none",
        "pause_reason": held(row, "pause_reason") or "none",
        "work_item": str(item_id) if item_id else None,
        "started": _epoch(created),
        # Labels of the run's counters, from memory (no database read per turn).
        "size_class": _size_class(held(row, "context")), "workflow_version": held(row, "workflow_version"),
    }
    if "waiting_kind" not in inspect(row).dict:
        fields.pop("waiting_kind")
    if "pause_reason" not in inspect(row).dict:
        fields.pop("pause_reason")

    def apply() -> None:
        now = time.time()
        if fields.get("status") in FINISHED_RUNS:
            fields["finished"] = now
        RUNS.update(str(run_id), now, **fields)

    return apply


def _size_class(context: Any) -> str | None:
    """The class the run started in (``context.size_class.initial``), else its current one; ``None`` when unknown."""
    entry = dict(context.get("size_class") or {}) if isinstance(context, dict) else {}
    value = entry.get("initial") or entry.get("class")
    return str(value) if value else None


def run_event_written(row: Any, session: Any) -> Callable[[], None] | None:
    run_id, kind = held(row, "run_id"), held(row, "kind")
    if not run_id or not kind:
        return None
    detail = held(row, "detail")
    detail = detail if isinstance(detail, dict) else {}
    phase = held(row, "node_id") or "none"
    extra: dict[str, Any] = {}
    if kind == "review_verdict":
        findings = detail.get("findings")
        if not isinstance(findings, int):
            listed = detail.get("finding_list")
            findings = len(listed) if isinstance(listed, list) else 0
        extra["review"] = (phase, str(detail.get("verdict") or "none"), str(detail.get("reviewer_engine") or "unknown"),
                           str(detail.get("reviewer_model") or "unknown"), findings)
    elif kind == "pipeline_reported":
        unproven = detail.get("unproven")
        extra["pipeline"] = (str(detail.get("state") or "unknown"), len(unproven) if isinstance(unproven, list) else 0)
    if kind == "node_entered":
        extra["phase"] = phase

    def apply() -> None:
        now = time.time()
        RUNS.update(str(run_id), now, last_event=(kind, now), **extra)

    return apply


def job_written(row: Any) -> Callable[[], None] | None:
    job_id = held(row, "id")
    if not job_id:
        return None
    usage = held(row, "usage")
    tokens = {kind: usage[key] for kind, key in JOB_USAGE_KEYS
              if isinstance(usage, dict) and isinstance(usage.get(key), int)}
    fields = {"engine": held(row, "engine") or "claude_code", "profile": held(row, "profile"),
              "model": held(row, "turn_model") or held(row, "model"), "status": held(row, "status"),
              "turn_state": held(row, "turn_state"), "turns": held(row, "turn_count"),
              "session": held(row, "session_id"), "tokens": tokens or None}

    def apply() -> None:
        JOBS.update(str(job_id), time.time(), **fields)

    return apply


def session_written(row: Any) -> Callable[[], None] | None:
    session_id = held(row, "id")
    if not session_id or "status" not in inspect(row).dict:
        return None
    fields = {"status": held(row, "status"), "agent_type": held(row, "agent_type") or "diagnosis"}
    return lambda: SESSIONS.update(str(session_id), time.time(), **fields)


def approval_written(row: Any) -> Callable[[], None] | None:
    approval_id = held(row, "id")
    if not approval_id:
        return None
    source = "session" if held(row, "session_id") else "task_run" if held(row, "task_run_id") else "review"
    status = held(row, "status") or "pending"
    return lambda: APPROVALS.update(str(approval_id), time.time(), source=source, status=status)



def usage_written(row: Any) -> Callable[[], None] | None:
    session_id = held(row, "session_id")
    tokens = {kind: int(held(row, column) or 0) for kind, column in TOKEN_TYPES}
    if not session_id or not any(tokens.values()):
        return None

    def apply() -> None:
        link = RUN_OF_SESSION.get(str(session_id))
        if link is None:
            return
        counted = dict(RUN_TOKENS.get(link[0]) or {})
        for kind, value in tokens.items():
            counted[kind] = counted.get(kind, 0) + value
        RUN_TOKENS.put(link[0], counted)

    return apply


def _epoch(value: Any) -> float | None:
    if value is None:
        return None
    from datetime import UTC

    return (value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp()
