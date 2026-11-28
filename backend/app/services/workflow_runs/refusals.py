"""A phase's reaction to repeated refusals, as workflow data: one mechanism for every "the phase cannot do this"
case."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from ..redaction_policy import redact_secret_text
from .records import record_event
from .states import PAUSE_PHASE_SCOPE_EXCEEDED

CONFIG_KEY = "refusals"
CONTEXT_KEY = "phase_refusals"
PENDING_KEY = "refusal_change_plan"
EVENT_REACTED = "phase_refusals_reacted"
ACTION_PAUSE, ACTION_ESCALATE, ACTION_CHANGE_PLAN, ACTION_CONTINUE = "pause", "escalate", "change_plan", "continue"
MAX_KEPT = 5


def intent(tool: str, tool_input: dict[str, Any]) -> str:
    command = str(tool_input.get("command") or "").split()
    if command:
        return f"{tool}:{' '.join(command[:2])}"
    return f"{tool}:{tool_input.get('file_path') or tool_input.get('path') or ''}"


def _matches(rule: dict[str, Any], tool: str, reason: str, tool_input: dict[str, Any]) -> bool:
    from ..engineering_knowledge.stacks import is_test

    wanted = rule.get("reason")
    if wanted and reason not in (wanted if isinstance(wanted, list) else [wanted]):
        return False
    if rule.get("tools") and tool not in list(rule["tools"]):
        return False
    path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    return not rule.get("test_file") or bool(path and is_test(path.lstrip("/")))


async def react(db: AsyncSession, run: WorkflowRun, *, tool: str, reason: str, tool_input: dict[str, Any],
                message: str = "") -> str:
    from .graph import graph_for_run

    tried = intent(tool, tool_input)
    state = dict(dict(run.context or {}).get(CONTEXT_KEY) or {})
    seen = {**dict(state.get("seen") or {}), tried: int(dict(state.get("seen") or {}).get(tried) or 0) + 1}
    state = {"counts": dict(state.get("counts") or {}), "requests": dict(state.get("requests") or {}), "seen": seen}
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    rules = [rule for rule in list(dict(getattr(node, "config", None) or {}).get(CONFIG_KEY) or [])
             if isinstance(rule, dict)]
    taken = ""
    for index, rule in enumerate(rules if node is not None else []):
        if not _matches(rule, tool, reason, tool_input):
            continue
        key = f"{node.id}:{index}:{tried}"
        counts, requests = dict(state["counts"]), dict(state["requests"])
        counts[key] = int(counts.get(key) or 0) + 1
        # Kept in run.context and shown in the pause: never a secret of the command.
        requests[key] = [*list(requests.get(key) or []), redact_secret_text(tool_input.get("command") or tool_input.get(
            "file_path") or tool)[:200]][-MAX_KEPT:]
        state = {**state, "counts": counts, "requests": requests}
        if counts[key] % max(int(rule.get("repeat") or 1), 1) == 0:
            run.context = {**dict(run.context or {}), CONTEXT_KEY: state}
            taken = await _act(db, run, node, rule, tried=tried, reason=reason, requests=requests[key],
                               message=message)
            break
    run.context = {**dict(run.context or {}), CONTEXT_KEY: state}
    return taken


def times_refused(run: WorkflowRun, tool: str, tool_input: dict[str, Any]) -> int:
    return int(dict(dict(dict(run.context or {}).get(CONTEXT_KEY) or {}).get("seen") or {}).get(
        intent(tool, tool_input)) or 0)


async def _act(db: AsyncSession, run: WorkflowRun, node: Any, rule: dict[str, Any], *, tried: str, reason: str,
               requests: list[str], message: str) -> str:
    from .limits import pause_run

    action = rule.get("action") or ACTION_PAUSE
    detail = {"intent": tried, "reason": reason, "refused": requests, "phase": node.id,
              **({"refusal": message[:500]} if message else {})}
    if action == ACTION_ESCALATE:
        from .size_class import escalate

        if escalate(db, run, cause=f"refusals:{tried}"):
            record_event(db, run, EVENT_REACTED, node_id=node.id, detail={**detail, "action": ACTION_ESCALATE})
            return ACTION_ESCALATE
        action = ACTION_PAUSE  # the class has no heavier one: a person decides
    target = str(action.get(ACTION_CHANGE_PLAN) or "") if isinstance(action, dict) else ""
    if target:
        from .graph import graph_for_run
        from .size_class.merge import landing

        target = landing(run, await graph_for_run(db, run), target)
    if target == node.id:
        # The agent already has the refusal: it goes on in this turn instead of re-entering the merged phase.
        record_event(db, run, EVENT_REACTED, node_id=node.id, detail={**detail, "action": ACTION_CONTINUE})
        return ACTION_CONTINUE
    if target:
        run.context = {**dict(run.context or {}), PENDING_KEY: {"node_id": target, "from": node.id,
                                                                "at": utc_now().isoformat(), **detail}}
    record_event(db, run, EVENT_REACTED, node_id=node.id,
                 detail={**detail, "action": ACTION_CHANGE_PLAN if target else ACTION_PAUSE,
                         **({"node_id": target} if target else {})})
    what = (f"goes back to '{target}' when this turn has ended" if target else
            "needs its own story or a change plan; continue with a reason, change the plan, or abort")
    await pause_run(db, run, reason=PAUSE_PHASE_SCOPE_EXCEEDED, actor_id=None, detail={
        "message": f"Phase '{node.title or node.id}' refused the same request {len(requests)} time(s) "
                   f"({tried}, {reason}): the work {what}.", **detail,
        "resume": {"kind": "restart", "node_id": target or node.id}})
    return ACTION_CHANGE_PLAN if target else ACTION_PAUSE


async def apply_pending_change_plan(db: AsyncSession, run: WorkflowRun) -> bool:
    from .engine import restart_at

    pending = dict(dict(run.context or {}).get(PENDING_KEY) or {})
    if not pending or run.pause_reason != PAUSE_PHASE_SCOPE_EXCEEDED:
        return False
    context = dict(run.context or {})
    context.pop(PENDING_KEY, None)
    context["change_plan_reason"] = {key: pending[key] for key in ("from", "intent", "reason", "refused", "refusal")
                                     if key in pending}
    run.context = context
    await restart_at(db, run, str(pending["node_id"]), actor_id=None)
    return True


__all__ = ["CONFIG_KEY", "EVENT_REACTED", "apply_pending_change_plan", "intent", "react", "times_refused"]
