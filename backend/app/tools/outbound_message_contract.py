"""The outbound-message contract: what a message to a person outside the session may contain.

A person approves every outbound message (``services/tool_approval_gate``, rule ``outbound_message``) and
must see exactly what is sent and to whom. So the values are bounded and shown in full: a value over its
limit, a recipient that is not one plain address, or a ticket id with whitespace or control characters
is refused before any preview, approval or send, never shortened. The same limits are the tool
schema's ``maxLength`` and the tool runtime's own check.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

MAX_QUESTION_CHARS = 2000
MAX_RECIPIENT_CHARS = 254  # RFC 5321 path limit
MAX_TICKET_ID_CHARS = 64

OUTBOUND_MESSAGE_INVALID = "outbound_message_invalid"

_RECIPIENT = re.compile(r"[^\s@,;<>\"']+@[^\s@,;<>\"']+\.[^\s@,;<>\"']+")
_TICKET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def outbound_message_problem(params: Mapping[str, Any] | None) -> str | None:
    """Why the parameters break the contract (``None`` when they keep it)."""
    values = params if isinstance(params, Mapping) else {}
    question = str(values.get("question") or "")
    recipient = str(values.get("reporter_email") or "")
    ticket_id = str(values.get("ticket_id") or "")
    if len(question) > MAX_QUESTION_CHARS:
        return f"question is longer than {MAX_QUESTION_CHARS} characters"
    if _CONTROL.search(question):
        return "question contains control characters"
    if len(recipient) > MAX_RECIPIENT_CHARS or not _RECIPIENT.fullmatch(recipient):
        return f"reporter_email must be one plain email address of at most {MAX_RECIPIENT_CHARS} characters"
    if len(ticket_id) > MAX_TICKET_ID_CHARS or not _TICKET_ID.fullmatch(ticket_id):
        return f"ticket_id must be one ticket key of at most {MAX_TICKET_ID_CHARS} characters"
    return None


def outbound_message_refusal(tool_name: str, params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The refusal result for parameters that break the contract, or ``None``."""
    problem = outbound_message_problem(params)
    if problem is None:
        return None
    return {
        "error": f"Message not sent: {problem}. Nothing was shown for approval or sent.",
        "error_code": OUTBOUND_MESSAGE_INVALID,
        "tool_name": tool_name,
    }


__all__ = [
    "MAX_QUESTION_CHARS",
    "MAX_RECIPIENT_CHARS",
    "MAX_TICKET_ID_CHARS",
    "OUTBOUND_MESSAGE_INVALID",
    "outbound_message_problem",
    "outbound_message_refusal",
]
