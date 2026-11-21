"""The seat analysis session: ``octryx-claude analyze <KEY>``.

A Workspace whose analysis setting is ``runner: seat`` analyses its work items in the user's own seat
session (their Claude subscription) instead of a governed server run. The launcher registers that session
with ``purpose: work_item_analysis`` and the item's key (``X-Octryx-Work-Item``). Registration is
refused, with a fixed reason, unless all of these hold:

- the session's profile is ``seat`` (``analysis_requires_seat``); the Workspace's seat policy, classification
  included, is checked by the registration route before (``seat_mode_forbidden``, ...);
- the Workspace's analysis runner is ``seat`` (``analysis_runner_not_seat``);
- the item key names exactly one work item of the Workspace (``analysis_work_item_required`` / ``_not_found``;
  a key two sources or instances share, e.g. the same Jira key in two Jira instances, is
  ``analysis_work_item_ambiguous``: the session is never pinned to an item chosen by order).

The registered session is pinned to that item (session metadata ``purpose`` and ``analysis_work_item_id``).
Its tools are fixed: the PreToolUse check (``agent_gateway.analysis_tools``) allows only the read-only
analysis tools on the platform's MCP server plus ``work_item_analysis_submit``; everything else, Claude
Code's own tools included, is denied. The platform's MCP server enforces the same set itself
(``seat_mcp_gate``): a connection whose session key names this session gets every other tool refused.

The citations of a submitted analysis are checked against the read tool runs the platform's MCP server
itself executed for this session (``ToolCall`` rows with ``parameters.source = "mcp_server"``, recorded by
``seat_mcp_gate``, bounded excerpts). ``tool_result`` blocks the client sends to the model gateway never count.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, Session, ToolCall, WorkItem
from .settings import RUNNER_SEAT, settings_from_config

PURPOSE_FIELD = "purpose"
PURPOSE_ANALYSIS = "work_item_analysis"
PURPOSE_METADATA = "gateway_purpose"
ITEM_METADATA = "analysis_work_item_id"
SUBMIT_TOOL = "work_item_analysis_submit"
# The read-only analysis tools of a seat analysis session, by their MCP name on the platform's server.
READ_TOOLS = (
    "knowledge_search",
    "knowledge_read",
    "work_item_context",
    "list_servicenow_incidents",
    "list_servicenow_changes",
    "list_servicenow_records",
    "get_servicenow_record",
)
SESSION_TOOLS = (*READ_TOOLS, SUBMIT_TOOL)
# ``ToolCall.parameters["source"]`` of a read tool run the platform's MCP server executed (``seat_mcp_gate``).
TOOL_CALL_SOURCE_MCP_SERVER = "mcp_server"
# The launcher names the platform's MCP server ``octryx-knowledge`` (``octryx_claude.launch``).
CLIENT_TOOL_PREFIX = "mcp__octryx-knowledge__"
CLIENT_SESSION_TOOLS = frozenset(f"{CLIENT_TOOL_PREFIX}{name}" for name in SESSION_TOOLS)

REASON_PURPOSE_INVALID = "purpose_invalid"
REASON_REQUIRES_SEAT = "analysis_requires_seat"
REASON_RUNNER_NOT_SEAT = "analysis_runner_not_seat"
REASON_ITEM_REQUIRED = "analysis_work_item_required"
REASON_ITEM_NOT_FOUND = "analysis_work_item_not_found"
REASON_ITEM_AMBIGUOUS = "analysis_work_item_ambiguous"
MAX_EVIDENCE_CALLS = 200


def requested_purpose(body: Mapping[str, Any]) -> str | None:
    """The registration body's purpose: ``None`` (a normal session) or the raw value."""
    value = body.get(PURPOSE_FIELD)
    return None if value in (None, "") else value


async def seat_runner_selected(db: AsyncSession, workspace_id: str) -> bool:
    project = await db.get(Project, workspace_id)
    settings, _source = settings_from_config(project.config if project is not None else None)
    return settings.runner == RUNNER_SEAT


async def items_by_key(db: AsyncSession, workspace_id: str, key: str) -> list[WorkItem]:
    """At most two work items of the Workspace with this key (two means the key is ambiguous)."""
    return list((await db.execute(select(WorkItem).where(WorkItem.project_id == workspace_id,
                                                         WorkItem.source_key == key).limit(2))).scalars().all())


async def registration_refusal(
    db: AsyncSession, *, workspace_id: str, work_item_key: str, body: Mapping[str, Any]
) -> tuple[str | None, WorkItem | None]:
    """``(refusal, None)`` or ``(None, pinned item)``; ``(None, None)`` for a session without a purpose."""
    purpose = requested_purpose(body)
    if purpose is None:
        return None, None
    if purpose != PURPOSE_ANALYSIS:
        return REASON_PURPOSE_INVALID, None
    if body.get("profile") != "seat":
        return REASON_REQUIRES_SEAT, None
    if not await seat_runner_selected(db, workspace_id):
        return REASON_RUNNER_NOT_SEAT, None
    if not work_item_key:
        return REASON_ITEM_REQUIRED, None
    items = await items_by_key(db, workspace_id, work_item_key)
    if not items:
        return REASON_ITEM_NOT_FOUND, None
    if len(items) > 1:
        return REASON_ITEM_AMBIGUOUS, None
    return None, items[0]


def pin_session(session: Session, item: WorkItem) -> None:
    metadata = dict(session.metadata_ or {})
    metadata[PURPOSE_METADATA] = PURPOSE_ANALYSIS
    metadata[ITEM_METADATA] = item.id
    session.metadata_ = metadata


def pinned_item_id(session: Session | None) -> str | None:
    """The work item an analysis session is pinned to, or ``None`` for any other session."""
    metadata = session.metadata_ if session is not None and isinstance(session.metadata_, dict) else {}
    if metadata.get(PURPOSE_METADATA) != PURPOSE_ANALYSIS:
        return None
    item_id = metadata.get(ITEM_METADATA)
    return item_id if isinstance(item_id, str) and item_id else None


async def observed_tool_outputs(db: AsyncSession, session_id: str) -> list[str]:
    """The excerpts of the read tools' successful results the platform's MCP server executed for the session."""
    rows = (await db.execute(
        select(ToolCall).where(
            ToolCall.session_id == session_id,
            ToolCall.tool_name.in_(READ_TOOLS),
            ToolCall.parameters["source"].as_string() == TOOL_CALL_SOURCE_MCP_SERVER,
        )
        .order_by(ToolCall.created_at).limit(MAX_EVIDENCE_CALLS)
    )).scalars().all()
    outputs = []
    for row in rows:
        result = row.result if isinstance(row.result, dict) else {}
        excerpt = result.get("excerpt")
        if result.get("is_error") is False and isinstance(excerpt, str) and excerpt:
            outputs.append(excerpt)
    return outputs


__all__ = [
    "CLIENT_SESSION_TOOLS",
    "PURPOSE_ANALYSIS",
    "READ_TOOLS",
    "SESSION_TOOLS",
    "SUBMIT_TOOL",
    "TOOL_CALL_SOURCE_MCP_SERVER",
    "observed_tool_outputs",
    "pin_session",
    "pinned_item_id",
    "registration_refusal",
]
