"""What a run learns, captured at event time (never by reading events back for a metric)."""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun
from ...redaction_policy import redact_secret_text
from .store import bounded, data, remember

OPEN_KEY = "run_memory_environment_open"
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


def environment_failed(run: WorkflowRun, failure: dict[str, Any]) -> None:
    """The pipeline paused ``environment_not_ready``: remember the error until a green pipeline passes it."""
    reason = bounded(failure.get("reason"))
    if reason:
        run.context = {**dict(run.context or {}), OPEN_KEY: {"error": reason, "node_id": run.current_node_id}}


async def pipeline_green(db: Any, run: WorkflowRun, results: list[dict[str, Any]], setup: str = "") -> None:
    """The commands that exited 0 in the pipeline; the open environment error, if any, with what ran past it."""
    green = [bounded(item.get("command")) for item in results
             if item.get("exit_code") == 0 and str(item.get("command") or "").strip()]
    for command in green:
        await remember(db, run, "test_command", command, {"command": command})
    opened = dict(dict(run.context or {}).get(OPEN_KEY) or {})
    if opened.get("error") and green:
        ran = "; ".join(item for item in [bounded(setup), *green] if item)
        await remember(db, run, "environment_fix", opened["error"][:80], {"error": opened["error"], "ran": ran})
        run.context = {key: value for key, value in dict(run.context or {}).items() if key != OPEN_KEY}


def _family(tool: str) -> str:
    return "edit" if tool in EDIT_TOOLS else tool


def _call(tool: str, tool_input: dict[str, Any]) -> str:
    # Kept in run memory and passed on as a correction: never a secret of the command.
    target = tool_input.get("command") or tool_input.get("file_path") or tool_input.get("path") or ""
    return bounded(redact_secret_text(f"{tool}: {target}"))


async def denial_answered(db: Any, run: WorkflowRun, hook_input: dict[str, Any]) -> None:
    """An allowed call: if the platform refused the same tool in this pass and no allowed call answered that refusal
    yet, keep the pair. One indexed query per allowed call of a run-bound session."""
    from sqlalchemy import select

    from ....models import WorkflowRunEvent

    tool = str(hook_input.get("tool_name") or "")
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    if not tool or not run.current_node_id:
        return
    entered = str(dict(run.node_state or {}).get("entered_at") or "")
    rows = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "tool_denied",
        WorkflowRunEvent.node_id == run.current_node_id).order_by(WorkflowRunEvent.created_at.desc()).limit(1)
    )).scalars().all()
    if not rows:
        return
    denial = rows[0]
    detail = dict(denial.detail or {})
    if (entered and denial.created_at is not None and denial.created_at.isoformat() < entered) or str(
            detail.get("reason") or "") not in data()["denial_reasons"]:
        return
    refused_tool = str(detail.get("tool") or "")
    if refused_tool and _family(refused_tool) != _family(tool):
        return
    if await answered_already(db, run, denial.id):
        return
    refused = bounded(redact_secret_text(detail.get("input") or detail.get("command") or detail.get("path") or ""))
    worked = _call(tool, tool_input)
    if not refused or refused in worked:
        return
    key = f"{detail.get('reason')}|{' '.join(refused.split()[:3])}"
    # No write to the run here: the tool check does not hold the run's claim; the entry carries the refusal's id.
    await remember(db, run, "denial_alternative", key, {
        "reason": str(detail.get("reason")), "refused": refused, "worked": worked, "denial_id": denial.id,
        "message": bounded(detail.get("message"))})
    from ..corrections import refused_call

    # Every answered refusal is a correction, a known one too: its repeats count.
    await refused_call(db, run, str(detail.get("reason")), refused, worked)


def _head(command: str) -> tuple[str, ...]:
    return tuple(command.split()[:2])


async def large_outputs(db: Any, session_id: str, tools: list[Any]) -> None:
    """A measured turn's large Bash results, kept with a later shorter run of the same command in that turn."""
    from sqlalchemy import select

    from ....models import WorkflowRun, WorkflowRunSession

    large = int(data()["large_output_kb"]) * 1024
    if not any(getattr(tool, "tool", "") == "Bash" and getattr(tool, "chars", 0) >= large for tool in tools):
        return
    run = (await db.execute(select(WorkflowRun).join(WorkflowRunSession, WorkflowRunSession.run_id == WorkflowRun.id)
                            .where(WorkflowRunSession.session_id == session_id).limit(1))).scalar_one_or_none()
    if run is not None:
        await remember_large(db, run, tools)


async def remember_large(db: Any, run: WorkflowRun, tools: list[Any]) -> None:
    large, small = int(data()["large_output_kb"]) * 1024, int(data()["short_output_kb"]) * 1024
    bash = [tool for tool in tools if getattr(tool, "tool", "") == "Bash" and getattr(tool, "label", "")]
    for tool in [item for item in bash if item.chars >= large]:
        command = bounded(tool.label)
        shorter = next((bounded(later.label) for later in bash if later.call > tool.call and later.chars <= small
                        and _head(later.label) == _head(tool.label) and later.label != tool.label), "")
        await remember(db, run, "large_output", command, {"command": command, "kb": (tool.chars + 1023) // 1024,
                                                           **({"shorter": shorter} if shorter else {})})


async def answered_already(db: Any, run: WorkflowRun, denial_id: str) -> bool:
    from .store import app_of, memory_of, record_of

    entries = memory_of(await record_of(db, run), app_of(run)).get("denial_alternative") or []
    return any(entry.get("denial_id") == denial_id for entry in entries)


__all__ = ["OPEN_KEY", "denial_answered", "environment_failed", "large_outputs", "pipeline_green", "remember_large"]
