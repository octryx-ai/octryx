"""PreToolUse rule of a seat analysis session: only the analysis tools run.

A session registered with ``purpose: work_item_analysis`` (``work_item_analysis.seat_session``) may call only
the read-only analysis tools of the platform's MCP server and ``work_item_analysis_submit``. Every other tool —
Claude Code's own Bash, Read, Edit, Write, WebFetch, other MCP servers, other platform tools — is denied here,
at the runtime boundary, whatever the launcher's flags asked for. Any other session is not affected.
"""

from __future__ import annotations

from typing import Any

from ...models import Session
from ..work_item_analysis.seat_session import CLIENT_SESSION_TOOLS, pinned_item_id
from .contract import STATE_DENIED
from .tool_check import DECISION_DENY, ToolDecision

REASON_ANALYSIS_TOOL_NOT_ALLOWED = "analysis_tool_not_allowed"
DENY_MESSAGE = (
    "This is a work item analysis session: only the read-only analysis tools (knowledge_search, knowledge_read, "
    "work_item_context, the ServiceNow read tools) and work_item_analysis_submit are available."
)


def analysis_tool_decision(session: Session, hook_input: dict[str, Any]) -> ToolDecision | None:
    """The denial for a tool outside the analysis set of an analysis session; ``None`` otherwise."""
    if pinned_item_id(session) is None:
        return None
    if str(hook_input.get("tool_name") or "") in CLIENT_SESSION_TOOLS:
        return None
    return ToolDecision(DECISION_DENY, STATE_DENIED, REASON_ANALYSIS_TOOL_NOT_ALLOWED, None, DENY_MESSAGE)


REASON_REVIEW_TOOL_NOT_ALLOWED = "review_tool_not_allowed"
REVIEW_DENY_MESSAGE = ("This is the independent reviewer's session of a workflow run: it has no tools. Answer from the "
                       "request alone.")


def review_tool_decision(session: Session, hook_input: dict[str, Any]) -> ToolDecision | None:
    """Every tool of the independent reviewer's seat session is denied (``workflow_runs.review.seat``): it reads only
    the facts the server put into its request, whatever tools its client offered."""
    from ..workflow_runs.review.seat_control import is_review_session

    if not is_review_session(session):
        return None
    return ToolDecision(DECISION_DENY, STATE_DENIED, REASON_REVIEW_TOOL_NOT_ALLOWED, None, REVIEW_DENY_MESSAGE)


__all__ = ["REASON_ANALYSIS_TOOL_NOT_ALLOWED", "REASON_REVIEW_TOOL_NOT_ALLOWED", "analysis_tool_decision",
           "review_tool_decision"]
