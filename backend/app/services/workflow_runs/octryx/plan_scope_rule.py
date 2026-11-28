"""The PreToolUse side of the plan scope. Codex cannot answer a hook's "ask", so both engines get the same deny
naming the path and class, and the run's ``needs_approval`` pause is where a person approves."""

from __future__ import annotations

from typing import Any

from ...agent_gateway.tool_check import DECISION_DENY, ToolDecision
from ..plan_scope import OUTSIDE, PLANNED, refusal

REASON_NEEDS_APPROVAL = "needs_approval"
RULE_PREFIX = "plan_scope"


def _message(kind: str, path: str, classes: list[str]) -> str:
    named = f" ({', '.join(classes)})" if classes else ""
    if kind == OUTSIDE:
        return (f"{path} is outside the approved plan's paths. The run waits for a person to approve this path; "
                "do not write it another way.")
    if kind == PLANNED:
        return f"{path} is an expensive path{named}: the run waits until a person approves the change plan."
    return (f"{path} is an expensive path{named} and the run has no approved plan for it. The run waits for a "
            "person to approve it; record the change plan (submit_change_plan) if this phase plans.")


def scope_decision(names: list[str], defaults: dict[str, Any] | None) -> ToolDecision | None:
    state, classes = dict(defaults or {}).get(RULE_PREFIX), dict(defaults or {}).get("expensive_paths")
    if not isinstance(state, dict) or not isinstance(classes, dict):
        return None
    kind, path, touched = refusal(names, state, classes)
    if not kind:
        return None
    return ToolDecision(DECISION_DENY, "denied", REASON_NEEDS_APPROVAL,
                        f"{RULE_PREFIX}:{kind}:{','.join(touched)}:{path}", _message(kind, path, touched))


def parsed(rule_id: str | None) -> dict[str, Any] | None:
    parts = str(rule_id or "").split(":", 3)
    if len(parts) != 4 or parts[0] != RULE_PREFIX:
        return None
    return {"kind": parts[1], "classes": [item for item in parts[2].split(",") if item], "path": parts[3]}


async def pause_for_approval(db: Any, run: Any, decision: ToolDecision) -> bool:
    from ..limits import pause_run
    from ..states import PAUSE_NEEDS_APPROVAL, STATUS_RUNNING

    detail = parsed(decision.rule_id)
    if detail is None or run.status != STATUS_RUNNING:
        return False
    await pause_run(db, run, reason=PAUSE_NEEDS_APPROVAL, actor_id=None, detail={
        **detail, "message": decision.message, "resume": {"kind": "continue", "node_id": run.current_node_id}})
    return True
