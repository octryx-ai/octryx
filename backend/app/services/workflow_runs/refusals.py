"""A phase's reaction to repeated refusals, as workflow data: one mechanism for every "the phase cannot do this"
case.

Examples: a bug-fix phase was refused ``outside_phase_tools`` three times for a dependency and for
code generation and spent its review loop; another fix phase was refused editing a protected test that asserts
the bug. A phase node may declare ``refusals``: a list of rules ``{reason, tools, test_file, repeat, action}``:

- ``reason`` (the refusal code or a list of them, e.g. ``outside_phase_tools`` / ``protected_path``), ``tools`` and
  ``test_file`` (the refused path is a test, ``stacks.is_test``) select the refusals a rule counts;
- the same *intent* (the tool plus the first two words of a command, else the tool and its path) is counted per run,
  across entries of the phase; at every ``repeat``-th refusal the rule's ``action`` runs:
  ``"pause"`` (the run pauses ``phase_scope_exceeded`` with the refused requests and the proposal of a story or a
  change plan), ``"escalate"`` (the run's size class one level up, ``size_class.escalate``; a class without one
  pauses instead), or ``{"change_plan": "<node>"}`` (the run pauses at once so the turn ends, then goes back to that
  node with the refusal as the reason when the turn has ended; a node the run's class merges into this phase or
  skips resolves to where the run would work, and when that is this phase the turn simply goes on).

Without ``refusals`` nothing happens: the engine ships no rule of its own.
"""

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
    """What the agent tried: the tool and the first two words of its command, else the tool and its path."""
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
    """Count this refusal for the run; the current phase's rules act on it. The action taken (``""`` for none).

    Counts that started at zero on every entry of the phase would let the same refusal come
    back after each change of plan without any rule reaching its count. They count per run and intent (``seen``); a
    rule acts at every ``repeat``-th refusal of its intent in its phase."""
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
    """How often the run was refused this intent, this time included."""
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
        # Example: the class merged 'reproduce' into this phase, so going back there
        # paused, restarted and re-entered this same phase with a new turn, three times in two minutes. The agent
        # already has the refusal; it goes on in this turn.
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
    """After the turn that was refused ended: go back to the rule's node (the run paused meanwhile)."""
    from .engine import restart_at

    pending = dict(dict(run.context or {}).get(PENDING_KEY) or {})
    if not pending or run.pause_reason != PAUSE_PHASE_SCOPE_EXCEEDED:
        return False
    context = dict(run.context or {})
    context.pop(PENDING_KEY, None)
    # The reason the next pass reads: the phase it came from and what was refused there.
    context["change_plan_reason"] = {key: pending[key] for key in ("from", "intent", "reason", "refused", "refusal")
                                     if key in pending}
    run.context = context
    await restart_at(db, run, str(pending["node_id"]), actor_id=None)
    return True


__all__ = ["CONFIG_KEY", "EVENT_REACTED", "apply_pending_change_plan", "intent", "react", "times_refused"]
