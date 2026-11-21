"""Workflow confirmations through Claude Code's own permission prompt.

A change-class workflow selected over MCP waits for a governed approval
(``services/mcp_workflow_tools``). The user grants it either in the Octryx UI, or in Claude
Code:

1. The agent calls the MCP tool ``workflow_confirm(approval_id)``. Claude Code runs the PreToolUse
   hook, which sends ``POST sessions/tool-check`` with a **confirmation proof**: an HMAC signed by
   the launcher's in-memory hook key (``hook_key.py``) over session key, tool_use id, approval id,
   nonce and time.
2. :func:`ask_for_confirmation` verifies the proof, refuses a reused nonce, and issues a
   **one-time ticket**. That is a random token whose sha256 is stored on a ``ToolCall`` row
   (``status="confirmation_asked"``) of the gateway session, bound to the approval id and the
   tool_use id and valid for :data:`TICKET_TTL_SECONDS`. It answers ``decision: "ask"`` with the
   token. The hook prints ``permissionDecision: "ask"`` and passes the token into the tool call
   (``updatedInput``), so Claude Code shows the user its permission prompt.
3. Only when the user accepts does Claude Code send the MCP call. Its ``_meta`` carries
   ``claudecode/toolUseId`` and its arguments carry the ticket. :func:`redeem_confirmation_ticket`
   accepts it only when all of these hold:
   - the ticket hash matches;
   - it is still pending and unexpired;
   - its approval and tool_use id match;
   - it is on the caller's own gateway session.

   Redeeming consumes the ticket.

A Bash process holding a gateway token cannot do any of this. It has no hook key, so it cannot
mint a ticket; it cannot redeem a ticket it never saw; and a reused nonce or ticket is refused. The
MCP side also refuses ``workflow_confirm`` outside the native MCP channel.

The hook tool name is exact: the launcher names the MCP server ``octryx-knowledge``, and
Claude Code calls its tools ``mcp__<server>__<tool>``. Nothing is matched by pattern.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, ToolCall
from ...time_utils import utc_now
from .contract import TOOL_CALL_SOURCE_HOOK
from .hook_key import ConfirmationProof, verify_confirmation_proof

WORKFLOW_CONFIRM_HOOK_TOOL = "mcp__octryx-knowledge__workflow_confirm"
# The governed approval of one workflow for one connection, on its own confirmation session.
CONFIRMATION_ACTION_PREFIX = "workflow_confirmation:"
CONFIRMATION_PURPOSE = "workflow_confirmation"
TOOL_CALL_STATUS_CONFIRMATION_ASKED = "confirmation_asked"
TOOL_CALL_STATUS_CONFIRMATION_CONSUMED = "confirmation_consumed"
TICKET_TTL_SECONDS = 600
DECISION_ASK = "ask"
STATE_NEEDS_CONFIRMATION = "needs_confirmation"
REASON_WORKFLOW_CONFIRMATION = "workflow_confirmation"
REASON_NONCE_REUSED = "confirmation_proof_replayed"
_TICKET_SCAN_LIMIT = 50

_ASK_MESSAGE = (
    "Octryx: confirm the governed workflow approval {approval_id}. Accepting lets this session run "
    "the workflow with its declared capability (changes in your workspace). Reject to stay read-only."
)


def confirmation_scope_for_session(session_key: str) -> str:
    """The confirmation scope of a launcher session (an MCP connection without one uses its grant)."""
    return f"session:{session_key}"


def confirmation_scope_for_grant(grant_id: str | None) -> str:
    return f"grant:{grant_id or 'none'}"


def is_workflow_confirmation(hook_input: dict[str, Any]) -> bool:
    return str(hook_input.get("tool_name") or "") == WORKFLOW_CONFIRM_HOOK_TOOL


def _ticket_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _deny(reason: str) -> dict[str, Any]:
    return {
        "decision": "deny",
        "state": "denied",
        "reason": reason,
        "rule_id": None,
        "message": "Octryx could not verify that this confirmation came from your session's hook.",
    }


async def _hook_rows(db: AsyncSession, session_id: str) -> list[ToolCall]:
    rows = await db.execute(
        select(ToolCall)
        .where(ToolCall.session_id == session_id, ToolCall.tool_name == WORKFLOW_CONFIRM_HOOK_TOOL)
        .order_by(ToolCall.created_at.desc())
        .limit(_TICKET_SCAN_LIMIT)
    )
    return list(rows.scalars().all())


async def ask_for_confirmation(
    db: AsyncSession, *, session: Session, session_key: str, hook_input: dict[str, Any]
) -> dict[str, Any]:
    """The PreToolUse answer for ``workflow_confirm``: ``ask`` with a one-time ticket, or deny. Flushes."""
    proof = verify_confirmation_proof(session, session_key=session_key, hook_input=hook_input)
    if not isinstance(proof, ConfirmationProof):
        return _deny(proof)
    rows = await _hook_rows(db, session.id)
    if any(isinstance(row.parameters, dict) and row.parameters.get("nonce") == proof.nonce for row in rows):
        return _deny(REASON_NONCE_REUSED)
    token = secrets.token_urlsafe(32)
    db.add(
        ToolCall(
            session_id=session.id,
            tool_name=WORKFLOW_CONFIRM_HOOK_TOOL,
            parameters={
                "source": TOOL_CALL_SOURCE_HOOK,
                "approval_id": proof.approval_id,
                "tool_use_id": proof.tool_use_id,
                "nonce": proof.nonce,
                "ticket_sha256": _ticket_hash(token),
                "expires_at": (utc_now() + timedelta(seconds=TICKET_TTL_SECONDS)).isoformat(),
            },
            result={"decision": DECISION_ASK},
            status=TOOL_CALL_STATUS_CONFIRMATION_ASKED,
        )
    )
    await db.flush()
    return {
        "decision": DECISION_ASK,
        "state": STATE_NEEDS_CONFIRMATION,
        "reason": REASON_WORKFLOW_CONFIRMATION,
        "rule_id": None,
        "message": _ASK_MESSAGE.format(approval_id=proof.approval_id),
        "confirmation_ticket": token,
    }


async def redeem_confirmation_ticket(
    db: AsyncSession, *, session: Session, approval_id: str, ticket: object, tool_use_id: object
) -> bool:
    """Consume the pending ticket for exactly this approval and tool_use id; ``False`` otherwise."""
    if type(ticket) is not str or not 0 < len(ticket) <= 128 or type(tool_use_id) is not str or not tool_use_id:
        return False
    digest = _ticket_hash(ticket)
    now = utc_now().isoformat()
    for row in await _hook_rows(db, session.id):
        parameters = row.parameters if isinstance(row.parameters, dict) else {}
        if not hmac.compare_digest(str(parameters.get("ticket_sha256") or ""), digest):
            continue
        valid = (
            row.status == TOOL_CALL_STATUS_CONFIRMATION_ASKED
            and parameters.get("approval_id") == approval_id
            and parameters.get("tool_use_id") == tool_use_id
            and str(parameters.get("expires_at") or "") > now
        )
        if not valid:
            return False
        row.status = TOOL_CALL_STATUS_CONFIRMATION_CONSUMED
        await db.flush()
        return True
    return False


__all__ = [
    "CONFIRMATION_ACTION_PREFIX",
    "CONFIRMATION_PURPOSE",
    "DECISION_ASK",
    "STATE_NEEDS_CONFIRMATION",
    "TICKET_TTL_SECONDS",
    "WORKFLOW_CONFIRM_HOOK_TOOL",
    "ask_for_confirmation",
    "confirmation_scope_for_grant",
    "confirmation_scope_for_session",
    "is_workflow_confirmation",
    "redeem_confirmation_ticket",
]
