"""The launcher side of a workflow confirmation, for contract tests: hook key and signed proofs.

It mirrors what octryx-claude's supervisor and PreToolUse hook do. The key exists only in the test
(as it exists only in the supervisor's memory), and a proof is the HMAC of the closed confirmation
message.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from app.services.agent_gateway.confirmation import WORKFLOW_CONFIRM_HOOK_TOOL
from app.services.agent_gateway.hook_key import proof_message, register_hook_key

STATE_ROOT = "/Users/dev/.octryx/claude"


def new_hook_key() -> bytes:
    return secrets.token_bytes(32)


async def register(db, session, key: bytes) -> str | None:
    raw = base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")
    return await register_hook_key(db, session=session, raw_key=raw, raw_state_root=STATE_ROOT)


def confirm_hook_input(
    key: bytes, *, session_key: str, approval_id: str, tool_use_id: str = "toolu_confirm_1",
    nonce: str | None = None, ts: int | None = None,
) -> dict:
    nonce = nonce or secrets.token_hex(16)
    ts = int(time.time()) if ts is None else ts
    message = proof_message(session_key, tool_use_id, approval_id, nonce, ts)
    mac = hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": WORKFLOW_CONFIRM_HOOK_TOOL,
        "tool_input": {"approval_id": approval_id},
        "tool_use_id": tool_use_id,
        "confirmation_proof": {"nonce": nonce, "ts": ts, "mac": mac},
    }


def decide_hook_input(
    key: bytes, *, session_key: str, run_id: str, tool_input: dict, tool_use_id: str = "toolu_decide_1",
    nonce: str | None = None,
) -> dict:
    """The PreToolUse input of a ``workflow_decide`` call with the launcher's ``decide`` proof over the run id."""
    from app.services.agent_gateway.decision_confirmation import WORKFLOW_DECIDE_HOOK_TOOL

    nonce = nonce or secrets.token_hex(16)
    ts = int(time.time())
    message = proof_message(session_key, tool_use_id, run_id, nonce, ts, "decide")
    mac = hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": WORKFLOW_DECIDE_HOOK_TOOL,
        "tool_input": {"run_id": run_id, **tool_input},
        "tool_use_id": tool_use_id,
        "confirmation_proof": {"nonce": nonce, "ts": ts, "mac": mac},
    }


__all__ = ["STATE_ROOT", "confirm_hook_input", "decide_hook_input", "new_hook_key", "register"]
