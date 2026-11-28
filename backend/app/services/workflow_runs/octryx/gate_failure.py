"""Why a failed gate sent the run back to its phase: the first thing the agent reads there."""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun

CONTEXT_KEY = "gate_failure"
MAX_DETAIL = 900


def record(run: WorkflowRun, *, gate: str, phase: str, failed: list[Any]) -> None:
    checks = "; ".join(
        f"{getattr(item, 'description', '') or getattr(item, 'type', '')}"
        + (f" ({item.detail})" if getattr(item, "detail", "") else "") for item in failed)
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {
        "gate": gate, "phase": phase, "failed": checks[:MAX_DETAIL] or "no blocking check could be judged",
        "shown": False}}


def clear(run: WorkflowRun) -> None:
    if CONTEXT_KEY in dict(run.context or {}):
        run.context = {key: value for key, value in dict(run.context or {}).items() if key != CONTEXT_KEY}


def current(run: WorkflowRun, node_id: str) -> dict[str, Any] | None:
    found = dict(dict(getattr(run, "context", None) or {}).get(CONTEXT_KEY) or {})
    return found if found and found.get("phase") == node_id else None


def back_prompt(run: WorkflowRun, node: Any, read_contract: str) -> str:
    from ..run_texts import run_text

    found = current(run, node.id)
    if found is None or found.get("shown"):
        return ""
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {**found, "shown": True}}
    return run_text("back_after_gate", phase=node.title, gate=found.get("gate") or "", failed=found.get("failed") or "",
                    read_contract=read_contract)


def stop_line(run: WorkflowRun, node_id: str) -> str:
    from ..run_texts import run_text

    found = current(run, node_id)
    return run_text("gate_failure.line", gate=found.get("gate") or "", failed=found.get("failed") or "") \
        if found else ""


__all__ = ["CONTEXT_KEY", "back_prompt", "clear", "current", "record", "stop_line"]
