"""The batched audit of a session that decides its tool calls on the device (``POST sessions/tool-audit``)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from .tool_check import DECISION_DENY, ToolDecision, record_denial
from .tool_execution import STATE_RECORDED, record_tool_execution

MAX_EVENTS = 500
EVENT_POST = "post"
EVENT_PRE = "pre"
LOCAL_RULE_PREFIX = "local:"
_REASON = re.compile(r"^[a-z0-9_]{1,64}$")
MAX_MESSAGE_CHARS = 600
SOURCE_LAUNCHER = "launcher"


async def record_tool_audit(db: AsyncSession, *, session: Session, events: Any) -> dict[str, Any]:
    recorded = denials = skipped = 0
    for event in list(events)[:MAX_EVENTS] if isinstance(events, list) else []:
        hook_input = event.get("hook_input") if isinstance(event, dict) else None
        if not isinstance(hook_input, dict):
            skipped += 1
            continue
        if event.get("event") == EVENT_POST:
            result = await record_tool_execution(db, session=session, hook_input=hook_input)
            recorded += result.state == STATE_RECORDED
            skipped += result.state != STATE_RECORDED
        elif event.get("event") == EVENT_PRE and event.get("decision") == DECISION_DENY:
            reason = str(event.get("reason") or "")
            reason = reason if _REASON.match(reason) else "local_decision"
            message = str(event.get("message") or "")[:MAX_MESSAGE_CHARS]
            decision = ToolDecision(DECISION_DENY, "denied", reason, LOCAL_RULE_PREFIX + reason, message)
            await record_denial(db, session=session, hook_input=hook_input, decision=decision)
            # Controls audit: the launcher's own denials reach the run's timeline and the metrics like
            # the server's (``tool_denied``, ``source: launcher``), not only a ToolCall row.
            from .tool_decision import _announce_denial  # noqa: PLC0415

            await _announce_denial(db, session, hook_input, decision, source=SOURCE_LAUNCHER)
            denials += 1
        else:
            skipped += 1
    if isinstance(events, list) and len(events) > MAX_EVENTS:
        skipped += len(events) - MAX_EVENTS
    return {"recorded": recorded, "denials": denials, "skipped": skipped}


__all__ = ["MAX_EVENTS", "record_tool_audit"]
