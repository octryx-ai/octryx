"""Why a failed gate sent the run back to its phase: the first thing the agent reads there.

Without it, a failed ``reproduces`` gate ("no new confirmed test") sent the run back to reproduce in the same turn.
The agent got the forward text ``run.next_phase`` ("The run moves on to
its next phase…") and then Stop answers listing the new pass's checks and every loop of the phase, including "The
reproduce check could not run" (a loop never taken). It never read why it was back, blamed the declared lint and the
run paused after four identical Stops.

When a gate after a phase fails, the engine keeps ``context.gate_failure`` (the gate, the phase, its failed checks
with their detail). Back in that phase:

- the prompt of the pass is ``run.back_after_gate`` (the failed checks first), once (``shown``);
- every Stop that finds the phase not done starts with ``run.gate_failure.line`` until the gate passes;
- a gate that passes, or a gate of another phase, clears it.
"""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun

CONTEXT_KEY = "gate_failure"
MAX_DETAIL = 900


def record(run: WorkflowRun, *, gate: str, phase: str, failed: list[Any]) -> None:
    """Keep the failed gate of ``phase`` (``failed``: its failed blocking check results)."""
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
    """``run.back_after_gate`` for the first pass back in ``node`` after its gate failed, once; ``""`` otherwise."""
    from ..run_texts import run_text

    found = current(run, node.id)
    if found is None or found.get("shown"):
        return ""
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {**found, "shown": True}}
    return run_text("back_after_gate", phase=node.title, gate=found.get("gate") or "", failed=found.get("failed") or "",
                    read_contract=read_contract)


def stop_line(run: WorkflowRun, node_id: str) -> str:
    """``run.gate_failure.line`` while the phase is back after its failed gate; ``""`` otherwise."""
    from ..run_texts import run_text

    found = current(run, node_id)
    return run_text("gate_failure.line", gate=found.get("gate") or "", failed=found.get("failed") or "") \
        if found else ""


__all__ = ["CONTEXT_KEY", "back_prompt", "clear", "current", "record", "stop_line"]
