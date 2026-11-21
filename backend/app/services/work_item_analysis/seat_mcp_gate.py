"""The platform MCP server's own gate and evidence ledger for a seat analysis session.

The PreToolUse rule (``agent_gateway.analysis_tools``) runs on the client. This module is the server-side
half, applied by every MCP dispatch of the platform's server (the native protocol through
``mcp_seat_analysis_guard``, the REST tool endpoint in ``api/routes/mcp_knowledge``):

- **Gate.** When the connection's launcher session key (``X-Octryx-Session``) names a session pinned
  to a work item analysis (``seat_session.pin_session``), any tool outside ``seat_session.SESSION_TOOLS`` is
  refused with ``analysis_tool_not_allowed`` before it runs. Nothing executes, nothing is recorded. The
  session's owner does not matter here: a key that names an analysis session only ever narrows the tools.
- **Evidence.** After one of the read tools (``seat_session.READ_TOOLS``) ran for the session's own user while
  the session is active, the server records what it returned as a ``ToolCall`` row of the session with
  ``parameters.source = "mcp_server"`` (bounded, redacted). ``seat_session.observed_tool_outputs`` reads only
  these rows, so the citations of a submitted analysis are checked against tool runs the server itself
  executed, never against ``tool_result`` blocks the client sent to the model gateway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, Session, ToolCall
from ..redaction_policy import redact_secret_text
from .seat_session import READ_TOOLS, SESSION_TOOLS, TOOL_CALL_SOURCE_MCP_SERVER, pinned_item_id

REASON_ANALYSIS_TOOL_NOT_ALLOWED = "analysis_tool_not_allowed"
MAX_EVIDENCE_EXCERPT_CHARS = 4_000
_MAX_SESSION_KEY_CHARS = 64
ANALYSIS_TOOL_REFUSAL: dict[str, str] = {
    "state": "denied",
    "reason": REASON_ANALYSIS_TOOL_NOT_ALLOWED,
    "error": (
        "This is a work item analysis session: only the read-only analysis tools and "
        "work_item_analysis_submit are available."
    ),
}


@dataclass(frozen=True, slots=True)
class PinnedAnalysis:
    """The analysis session a connection's session key names."""

    session_id: str
    user_id: str
    active: bool


async def pinned_analysis(db: AsyncSession, session_key: str | None) -> PinnedAnalysis | None:
    """The pinned analysis session of ``session_key``, or ``None`` (no key, unknown key, any other session)."""
    key = session_key.strip()[:_MAX_SESSION_KEY_CHARS] if isinstance(session_key, str) else ""
    if not key:
        return None
    presence = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == key))).scalar_one_or_none()
    if presence is None or not presence.session_id:
        return None
    session = await db.get(Session, presence.session_id)
    if pinned_item_id(session) is None:
        return None
    return PinnedAnalysis(str(session.id), str(presence.user_id), presence.stopped_at is None)


def analysis_tool_refusal(pinned: PinnedAnalysis | None, tool_name: str) -> dict[str, str] | None:
    """The closed refusal of a tool outside the analysis set of a pinned session; ``None`` otherwise."""
    if pinned is None or tool_name in SESSION_TOOLS:
        return None
    return dict(ANALYSIS_TOOL_REFUSAL)


def record_server_evidence(
    db: AsyncSession, pinned: PinnedAnalysis | None, *, user_id: str, tool_name: str, text: str, is_error: bool
) -> bool:
    """Record one read tool run the server executed for the pinned session's own user; ``True`` when recorded."""
    if pinned is None or not pinned.active or pinned.user_id != str(user_id) or tool_name not in READ_TOOLS:
        return False
    db.add(
        ToolCall(
            session_id=pinned.session_id,
            tool_name=tool_name,
            parameters={"source": TOOL_CALL_SOURCE_MCP_SERVER},
            result={"is_error": bool(is_error),
                    "excerpt": redact_secret_text(text or "", max_chars=MAX_EVIDENCE_EXCERPT_CHARS)},
            status="error" if is_error else "success",
        )
    )
    return True


def result_is_error(result: Any) -> bool:
    """A platform tool result is an error when it is not a mapping or carries ``error``."""
    return not isinstance(result, dict) or "error" in result


__all__ = [
    "ANALYSIS_TOOL_REFUSAL",
    "REASON_ANALYSIS_TOOL_NOT_ALLOWED",
    "PinnedAnalysis",
    "analysis_tool_refusal",
    "pinned_analysis",
    "record_server_evidence",
    "result_is_error",
]
