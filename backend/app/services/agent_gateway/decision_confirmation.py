"""Workflow run decisions through Claude Code's own permission prompt.

The requester may answer a user confirmation, a user conversation or a paused run of the run their session follows
from the terminal (``workflow_runs/octryx/decisions``). The agent can never answer for them, in any permission mode:

1. The agent calls the MCP tool ``workflow_decide(run_id, action, payload_hash, …)``. Claude Code runs the PreToolUse
   hook, which sends ``POST sessions/tool-check`` with a **decision proof**: the launcher's hook-key HMAC (verb
   ``decide``, bound to session key, tool_use id, run id, nonce and time; ``hook_key.verify_decision_proof``).
2. :func:`ask_for_decision` verifies the proof, refuses a reused nonce, and checks the decision itself before the
   user is asked: the session's own run, the user's right to act on it, a node the requester may answer, an action
   it offers and the current payload hash. Only then it issues a **one-time ticket** (sha256 on a ``ToolCall`` of the
   gateway session, bound to run, action, payload hash, the typed inputs' digest and the tool_use id) and answers
   ``ask`` with the exact payload as the prompt's text, payload hash first. A decision whose full text (payload,
   reply, criteria) does not fit the prompt is refused (``decide_in_platform`` with the link): never a decision on a
   partly shown payload. Nonce and ticket are looked up among all of the session's decision rows. The hook
   prints ``permissionDecision: "ask"``, so Claude Code shows the user its permission prompt (the launcher disables
   bypass mode; an "ask" is never auto-allowed).
3. Only when the user accepts does the MCP call run, carrying the ticket. :func:`redeem_decision_ticket` accepts it
   only for exactly that run, action, payload hash, inputs and tool_use id on the caller's own gateway session, still
   pending and unexpired, and consumes it. Without a redeemed ticket the MCP tool decides nothing.

A Bash process with a gateway token has no hook key, never sees a ticket, and cannot replay a nonce or a ticket.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, ToolCall, User
from ...time_utils import utc_now
from .confirmation import (
    DECISION_ASK,
    STATE_NEEDS_CONFIRMATION,
    TICKET_TTL_SECONDS,
    TOOL_CALL_STATUS_CONFIRMATION_ASKED,
    TOOL_CALL_STATUS_CONFIRMATION_CONSUMED,
    _ticket_hash,
)
from .contract import TOOL_CALL_SOURCE_HOOK
from .hook_key import ConfirmationProof, verify_decision_proof

WORKFLOW_DECIDE_HOOK_TOOL = "mcp__octryx-knowledge__workflow_decide"
REASON_DECISION_CONFIRMATION = "workflow_decision_confirmation"
REASON_NONCE_REUSED = "confirmation_proof_replayed"
REASON_RUN_NOT_BOUND = "decision_run_not_bound"
REASON_DECIDE_IN_PLATFORM = "decide_in_platform"


def is_workflow_decision(hook_input: dict[str, Any]) -> bool:
    return str(hook_input.get("tool_name") or "") == WORKFLOW_DECIDE_HOOK_TOOL


def _deny(reason: str, message: str | None = None) -> dict[str, Any]:
    return {"decision": "deny", "state": "denied", "reason": reason, "rule_id": None,
            "message": message or "Octryx could not verify that this decision came from your session's hook."}


async def _hook_rows(db: AsyncSession, session_id: str, field: str, value: str) -> list[ToolCall]:
    """The session's decision rows whose ``field`` is ``value``: a lookup, not a window of recent rows."""
    rows = await db.execute(
        select(ToolCall).where(ToolCall.session_id == session_id, ToolCall.tool_name == WORKFLOW_DECIDE_HOOK_TOOL,
                               ToolCall.parameters[field].as_string() == value)
    )
    return list(rows.scalars().all())


async def ask_for_decision(
    db: AsyncSession, *, session: Session, session_key: str, hook_input: dict[str, Any]
) -> dict[str, Any]:
    """The PreToolUse answer for ``workflow_decide``: ``ask`` with a one-time ticket and the exact payload, or deny."""
    from ..workflow_runs.access import run_access
    from ..workflow_runs.octryx.contract import run_contract
    from ..workflow_runs.octryx.decisions import arguments_digest, ask_text, check_decision, pending_decision
    from ..workflow_runs.records import WorkflowRunError, active_run_for_session

    proof = verify_decision_proof(session, session_key=session_key, hook_input=hook_input)
    if not isinstance(proof, ConfirmationProof):
        return _deny(proof)
    if await _hook_rows(db, session.id, "nonce", proof.nonce):
        return _deny(REASON_NONCE_REUSED)
    run = await active_run_for_session(db, session.id)
    user = await db.get(User, session.user_id)
    if run is None or run.id != proof.approval_id or user is None or await run_access(db, run, user) != "write":
        return _deny(REASON_RUN_NOT_BOUND, "This session follows no such workflow run you may act on.")
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    action, hash_value = str(tool_input.get("action") or ""), str(tool_input.get("payload_hash") or "")
    decision = await pending_decision(db, run)
    try:
        check_decision(decision, action=action, hash_value=hash_value)
    except WorkflowRunError as error:
        return _deny(error.code, str(error))
    text = ask_text(run, decision, action=action, arguments=tool_input)
    if text is None:
        # Never a decision on a partly shown payload or reply: too long for the prompt, so the platform decides.
        link = (await run_contract(db, run)).get("link")
        return {**_deny(REASON_DECIDE_IN_PLATFORM, "This decision is too long to show in full in the permission "
                        f"prompt; decide it in Octryx{': ' + link if link else ''}."),
                "state": "needs_clarification"}
    token = secrets.token_urlsafe(32)
    db.add(ToolCall(
        session_id=session.id, tool_name=WORKFLOW_DECIDE_HOOK_TOOL,
        parameters={"source": TOOL_CALL_SOURCE_HOOK, "run_id": run.id, "action": action, "payload_hash": hash_value,
                    "arguments_digest": arguments_digest(tool_input), "tool_use_id": proof.tool_use_id,
                    "nonce": proof.nonce, "ticket_sha256": _ticket_hash(token),
                    "expires_at": (utc_now() + timedelta(seconds=TICKET_TTL_SECONDS)).isoformat()},
        result={"decision": DECISION_ASK, "message": text}, status=TOOL_CALL_STATUS_CONFIRMATION_ASKED,
    ))
    await db.flush()
    return {"decision": DECISION_ASK, "state": STATE_NEEDS_CONFIRMATION, "reason": REASON_DECISION_CONFIRMATION,
            "rule_id": None, "message": text, "confirmation_ticket": token}


async def redeem_decision_ticket(
    db: AsyncSession, *, session: Session, run_id: str, action: str, payload_hash: str, arguments_digest: str,
    ticket: object, tool_use_id: object,
) -> bool:
    """Consume the pending ticket for exactly this decision and tool_use id; ``False`` otherwise."""
    if type(ticket) is not str or not 0 < len(ticket) <= 128 or type(tool_use_id) is not str or not tool_use_id:
        return False
    digest = _ticket_hash(ticket)
    now = utc_now().isoformat()
    expected = {"run_id": run_id, "action": action, "payload_hash": payload_hash,
                "arguments_digest": arguments_digest, "tool_use_id": tool_use_id}
    for row in await _hook_rows(db, session.id, "ticket_sha256", digest):
        parameters = row.parameters if isinstance(row.parameters, dict) else {}
        if not hmac.compare_digest(str(parameters.get("ticket_sha256") or ""), digest):
            continue
        if (row.status != TOOL_CALL_STATUS_CONFIRMATION_ASKED or str(parameters.get("expires_at") or "") <= now
                or any(parameters.get(name) != value for name, value in expected.items())):
            return False
        row.status = TOOL_CALL_STATUS_CONFIRMATION_CONSUMED
        await db.flush()
        return True
    return False


async def device_decision_preview(db: AsyncSession, *, owner_user_id: str, tool: str, preview: str) -> str | None:
    """The full ask text for a device job's approval of ``workflow_decide`` (the device only sees the tool input):
    the newest pending ask of the owner's sessions for that run, action and payload hash; ``None`` otherwise."""
    import json

    if tool != WORKFLOW_DECIDE_HOOK_TOOL:
        return None
    try:
        shown = json.loads(preview)
    except ValueError:
        return None
    if not isinstance(shown, dict):
        return None
    row = (await db.execute(
        select(ToolCall).join(Session, Session.id == ToolCall.session_id).where(
            Session.user_id == owner_user_id, ToolCall.tool_name == WORKFLOW_DECIDE_HOOK_TOOL,
            ToolCall.status == TOOL_CALL_STATUS_CONFIRMATION_ASKED,
            ToolCall.parameters["run_id"].as_string() == str(shown.get("run_id") or ""),
            ToolCall.parameters["action"].as_string() == str(shown.get("action") or ""),
            ToolCall.parameters["payload_hash"].as_string() == str(shown.get("payload_hash") or ""),
        ).order_by(ToolCall.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    message = dict(row.result or {}).get("message") if row is not None else None
    return message if isinstance(message, str) and message else None


__all__ = ["WORKFLOW_DECIDE_HOOK_TOOL", "ask_for_decision", "device_decision_preview", "is_workflow_decision",
           "redeem_decision_ticket"]
