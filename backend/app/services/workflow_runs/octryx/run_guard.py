"""Stop a device phase turn that runs in circles."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ToolCall, WorkflowRun

CODE_AGENT_LOOP = "agent_loop"
REASON_AGENT_LOOP = "workflow_run_agent_loop"
NOOP_WINDOW = 8
NOOP_LIMIT = 6
REPEAT_WINDOW = 12
REPEAT_LIMIT = 4
SHELL_TOOLS = frozenset({"Bash", "bash", "shell"})
_NOOP_PART = re.compile(r"""^\s*(?:echo|printf|true|:)(?:\s+(?:"[^"`$]*"|'[^']*'|[^\s;&|`$<>()]+))*\s*$""")


def _input(row: ToolCall) -> dict[str, Any]:
    parameters = row.parameters if isinstance(row.parameters, dict) else {}
    value = parameters.get("input")
    return value if isinstance(value, dict) else {}


def noop_shell(tool_name: str, tool_input: dict[str, Any]) -> bool:
    if tool_name not in SHELL_TOOLS:
        return False
    command = str(tool_input.get("command") or "").strip()
    if not command:
        return False
    parts = [part for part in re.split(r"&&|;|\n", command) if part.strip()]
    return bool(parts) and all(_NOOP_PART.match(part) for part in parts)


def once_per_call(rows: Sequence[ToolCall]) -> list[tuple[str, dict[str, Any]]]:
    # A denied call is recorded twice (denied_by_policy and error) and must count once for the loop check.
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    for row in rows:
        parameters = row.parameters if isinstance(row.parameters, dict) else {}
        key = str(parameters.get("tool_use_id") or row.id)
        data = _input(row)
        if data or key not in calls:
            calls[key] = (row.tool_name, data) if data or key not in calls else calls[key]
    # A call recorded only as "requested" (no input yet) says nothing about a repeat.
    return [call for call in calls.values() if call[1]]


def loop_kind(calls: Sequence[tuple[str, dict[str, Any]]]) -> str | None:
    recent = list(calls)[-NOOP_WINDOW:]
    if len(recent) >= NOOP_LIMIT and sum(noop_shell(name, data) for name, data in recent) >= NOOP_LIMIT:
        return "noop"
    counts: dict[str, int] = {}
    for name, data in list(calls)[-REPEAT_WINDOW:]:
        key = name + json.dumps(data, sort_keys=True, default=str)
        counts[key] = counts.get(key, 0) + 1
        if counts[key] >= REPEAT_LIMIT:
            return "repeat"
    return None


def _since(run: WorkflowRun) -> datetime | None:
    try:
        return datetime.fromisoformat(str(dict(run.node_state or {}).get("entered_at") or "")).replace(tzinfo=None)
    except ValueError:
        return None


def _paused_for_loop(run: WorkflowRun) -> bool:
    pause = dict(dict(run.node_state or {}).get("pause") or {})
    return run.status == "paused" and pause.get("code") == CODE_AGENT_LOOP


async def device_loop_refusal(db: AsyncSession, session_id: str) -> str | None:
    from ..limits import pause_run
    from ..records import active_run_for_session, lock_run
    from ..states import PAUSE_RUNTIME_FAILED, STATUS_RUNNING

    run = await active_run_for_session(db, session_id)
    if run is None:
        return None
    if _paused_for_loop(run):
        return REASON_AGENT_LOOP
    if run.status != STATUS_RUNNING:
        return None
    query = select(ToolCall).where(ToolCall.session_id == session_id)
    since = _since(run)
    if since is not None:
        query = query.where(ToolCall.created_at >= since)
    rows = list((await db.execute(query.order_by(ToolCall.created_at.desc()).limit(REPEAT_WINDOW * 2))).scalars())
    kind = loop_kind(once_per_call(list(reversed(rows)))[-REPEAT_WINDOW:])
    if kind is None:
        return None
    run = await lock_run(db, run)
    if run.status != STATUS_RUNNING:
        return None
    what = ("only printed messages (echo/printf) instead of working or ending its turn" if kind == "noop"
            else "called the same tool with the same input again and again")
    await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
        "message": (f"The agent {what}; the platform stopped its turn to save tokens. What it changed so far stays. "
                    "Run the phase again, change the plan, or abort the run."),
        "code": CODE_AGENT_LOOP, "loop": kind, "resume": {"kind": "restart", "node_id": run.current_node_id},
    })
    await db.commit()
    return REASON_AGENT_LOOP


__all__ = ["CODE_AGENT_LOOP", "REASON_AGENT_LOOP", "device_loop_refusal", "loop_kind", "noop_shell", "once_per_call"]
