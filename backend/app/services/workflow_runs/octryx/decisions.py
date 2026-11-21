"""Requester decisions of a workflow run answered from the terminal.

What the run waits for is the workflow definition's node, and only the node decides who may answer:

- **user confirmation** (test contract, ticket draft, reproduction, retry, advance, questions — and "go on" after a
  watched state was met) and **user conversation** nodes are the requester's: the terminal may answer them;
- a **paused** run (loop limit, budget, timeout) is continued with +k, re-planned or aborted by the requester (or the
  Work item owner / an admin, as in the platform): the terminal may answer it too;
- an **approval** node (four-eyes) and a held platform action's **tool approval** are another person's or the
  platform card's: platform only, the terminal shows the link;
- **watch**, **review** and **sub-workflow** waits are external state: nobody answers them, the agent least of all.

:func:`pending_decision` describes the open decision with the payload and the payload hash the platform card decides
on (a confirmation: exactly the waiting payload and its hash; a reply or a pause: the hash of the question or pause
it answers). :func:`decide_in_terminal` refuses a node not answerable by the requester, an action the node does not
offer and a payload that changed, then applies the decision through the platform's own service function
(``actions.perform_action`` → ``hitl_decisions.decide`` / ``pause``; ``hitl.record_reply``), so it is recorded,
audited and Workspace-scoped exactly like a decision in the run card. Whether the user really decided is the
caller's proof (the PreToolUse-confirmed ticket, ``agent_gateway/decision_confirmation``).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Message, User, WorkflowRun
from ..graph import NODE_APPROVAL, NODE_CONFIRMATION, NODE_CONVERSATION, NODE_WATCH, graph_for_run
from ..pause import payload_hash
from ..records import WorkflowRunError, lock_run, main_session_id, record_event
from ..states import (
    STATUS_PAUSED,
    STATUS_WAITING,
    WAITING_APPROVAL,
    WAITING_CONFIRMATION,
    WAITING_REPLY,
    WAITING_REVIEW,
    WAITING_SUB_WORKFLOW,
    WAITING_TOOL_APPROVAL,
    WAITING_WATCH,
)

KIND_CONFIRMATION = "user_confirmation"
KIND_CONVERSATION = "user_conversation"
KIND_PAUSE = "pause"
ACTION_REPLY = "reply"
EVENT_TERMINAL_DECISION = "terminal_decision"
PAUSE_ACTIONS = ("continue", "retry_action", "change_plan", "abort")
CONFIRM_ACTIONS = ("confirm", "change", "stop")
MAX_REPLY_CHARS = 100_000
# The whole ask text must fit the launcher's prompt (``hooks.MAX_ASK_CHARS``) and a device approval's preview
# (``devices.jobs.MAX_PREVIEW_CHARS``); a longer one is refused, never cut.
ASK_TEXT_LIMIT = 2000

_OTHER_PERSON = {WAITING_APPROVAL: "approval", WAITING_TOOL_APPROVAL: "tool_approval"}
_NOBODY = {WAITING_WATCH: "watch", WAITING_REVIEW: "review", WAITING_SUB_WORKFLOW: "sub_workflow"}


def _waiting(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.node_state or {}).get("waiting") or {})


async def _pause_decision(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    from ..actions import _pause_actions

    state = dict(run.node_state or {})
    pause = dict(state.get("pause") or {})
    payload = {"reason": run.pause_reason, "detail": pause.get("message"), "edge_id": pause.get("edge_id"),
               "node_id": run.current_node_id, "entry": state.get("entry")}
    offered = {item["key"]: item for item in await _pause_actions(db, run) if item["key"] in PAUSE_ACTIONS}
    inputs = {key: item["input"] for key, item in offered.items() if item.get("input")}
    return {"kind": KIND_PAUSE, "in_terminal": True, "subject": run.pause_reason, "payload": payload,
            "payload_hash": payload_hash(payload), "actions": [*offered, "abort"], "inputs": inputs}


async def pending_decision(db: AsyncSession, run: WorkflowRun, *, principal=None) -> dict[str, Any] | None:
    """The run's open decision and who may take it; ``None`` while nothing waits for a person."""
    if run.status == STATUS_PAUSED:
        return await _pause_decision(db, run)
    if run.status != STATUS_WAITING:
        return None
    kind = run.waiting_kind or ""
    if kind in _OTHER_PERSON:
        return {"kind": _OTHER_PERSON[kind], "in_terminal": False, "actions": []}
    if kind in _NOBODY or kind not in (WAITING_CONFIRMATION, WAITING_REPLY):
        return {"kind": _NOBODY.get(kind, kind), "in_terminal": False, "actions": []}
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    waiting = _waiting(run)
    from ..specification.integration import projected_node_state, protected_waiting

    if await protected_waiting(db, run):
        waiting = dict((await projected_node_state(db, run, principal=principal)).get("waiting") or {})
    # A met watch asks the requester "go on?" (``watch.record_condition``); an unmet one is external state.
    if kind == WAITING_CONFIRMATION and node is not None and node.kind in (NODE_CONFIRMATION, NODE_WATCH):
        payload = dict(waiting.get("payload") or {})
        actions = list(CONFIRM_ACTIONS)
        if payload.get("missing") or payload.get("blockers"):
            actions = actions[1:]  # nothing complete to confirm yet (as in the run card)
        return {"kind": KIND_CONFIRMATION, "in_terminal": True, "subject": waiting.get("subject") or "advance",
                "payload": payload, "payload_hash": str(waiting.get("payload_hash") or ""), "actions": actions}
    if kind == WAITING_REPLY and node is not None and node.kind == NODE_CONVERSATION:
        from ..hitl_actions import reply_payload

        payload = reply_payload(run)
        return {"kind": KIND_CONVERSATION, "in_terminal": True, "subject": "reply", "payload": payload,
                "payload_hash": payload_hash(payload), "actions": [ACTION_REPLY]}
    # The waiting state does not match a requester node of the definition: never answerable here.
    return {"kind": node.kind if node is not None and node.kind == NODE_APPROVAL else kind, "in_terminal": False,
            "actions": []}


def decision_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """The typed decision inputs the permission prompt shows and the ticket binds (nothing else is read)."""
    bound: dict[str, Any] = {}
    if isinstance(arguments.get("k"), int) and not isinstance(arguments.get("k"), bool):
        bound["k"] = arguments["k"]
    if isinstance(arguments.get("reply"), str) and arguments["reply"].strip():
        bound["reply"] = arguments["reply"].strip()[:MAX_REPLY_CHARS]
    if isinstance(arguments.get("reason"), str) and arguments["reason"].strip():
        bound["reason"] = " ".join(arguments["reason"].split())[:500]  # why an abort / stop stops the run
    criteria = arguments.get("human_verified_criteria")
    if isinstance(criteria, list):
        bound["human_verified_criteria"] = [str(item)[:200] for item in criteria[:50]]
    return bound


def arguments_digest(arguments: dict[str, Any]) -> str:
    return payload_hash(decision_arguments(arguments))


def ask_text(run: WorkflowRun, decision: dict[str, Any], *, action: str, arguments: dict[str, Any]) -> str | None:
    """What Claude Code's permission prompt shows, in full: the payload hash first, then the run, the node, the
    action, the typed inputs and the exact payload. ``None`` when it does not fit the prompt (:data:`ASK_TEXT_LIMIT`):
    a decision is never taken on a partly shown payload or reply — it is decided in the platform then."""
    from ..hitl_actions import CONFIRMATION_LABELS

    labels = CONFIRMATION_LABELS.get(str(decision.get("subject") or ""), {})
    label = {"confirm": labels.get("confirmed"), "change": labels.get("changed"), "stop": labels.get("stopped")}.get(
        action) or action
    payload = json.dumps(decision.get("payload") or {}, sort_keys=True, default=str)
    inputs = decision_arguments(arguments)
    text = (f"Payload {decision.get('payload_hash')}. Octryx: decide for yourself in workflow run "
            f"{run.workflow_key} ({run.id}) — {decision['kind']} '{decision.get('subject') or ''}': {label}"
            f"{' ' + json.dumps(inputs, sort_keys=True) if inputs else ''}. Payload: {payload}. "
            "Accept only if this is your decision; reject to leave it open.")
    return text if len(text) <= ASK_TEXT_LIMIT else None


def check_decision(decision: dict[str, Any] | None, *, action: str, hash_value: str) -> None:
    """Refuse a node not answerable here, an action it does not offer, or a payload that changed."""
    if decision is None:
        raise WorkflowRunError("nothing_to_decide", "The run waits for no decision.", 409)
    if not decision.get("in_terminal"):
        raise WorkflowRunError("platform_only", f"This decision ({decision.get('kind')}) is not the requester's to "
                                                "take here; it is decided in Octryx or by external state.", 403)
    if action not in decision.get("actions") or []:
        raise WorkflowRunError("action_not_offered", f"'{action}' is not offered for this decision; offered: "
                                                     f"{', '.join(decision.get('actions') or [])}.", 422)
    if not hash_value or hash_value != decision.get("payload_hash"):
        raise WorkflowRunError("payload_changed", "What you decide on changed; read the current decision and "
                                                  "decide again.", 409)


async def decide_in_terminal(db: AsyncSession, run: WorkflowRun, *, user: User, action: str, hash_value: str,
                             arguments: dict[str, Any]) -> WorkflowRun:
    """Apply a confirmed terminal decision through the platform's own decision functions; raises on refusal."""
    from ..actions import perform_action
    from ..hitl import record_reply

    run = await lock_run(db, run)
    # The actual terminal caller's own projection: a withheld payload offers no hash to decide on.
    decision = await pending_decision(db, run, principal=user)
    check_decision(decision, action=action, hash_value=hash_value)
    inputs = decision_arguments(arguments)
    # The decision record is the run card's; the channel is a separate event (audit: it came from the terminal).
    channel = {"channel": "terminal", "kind": decision["kind"], "action": action, "payload_hash": hash_value}
    node_id = run.current_node_id
    if action == ACTION_REPLY:
        from ..decider import require_node_decider

        await require_node_decider(db, run, user)
        if not inputs.get("reply"):
            raise WorkflowRunError("reply_required", "A reply needs its text.", 422)
        session_id = await main_session_id(db, run)
        if session_id and user.id == run.requested_by:  # role decisions do not write another person's thread
            db.add(Message(session_id=session_id, role="user", content=inputs["reply"]))
        await record_reply(db, run, inputs["reply"], user=user)
        record_event(db, run, EVENT_TERMINAL_DECISION, node_id=node_id, actor_id=user.id, detail=channel)
        return run
    body: dict[str, Any] = {"action": action, "payload_hash": hash_value}
    if "k" in inputs:
        body["k"] = inputs["k"]
    if "human_verified_criteria" in inputs:
        body["human_verified_criteria"] = inputs["human_verified_criteria"]
    if "reason" in inputs:
        body["reason"] = inputs["reason"]
    await perform_action(db, run, user=user, body=body)
    record_event(db, run, EVENT_TERMINAL_DECISION, node_id=node_id, actor_id=user.id, detail=channel)
    return run


__all__ = ["ACTION_REPLY", "ASK_TEXT_LIMIT", "arguments_digest", "ask_text", "check_decision", "decide_in_terminal",
           "decision_arguments", "pending_decision"]
