"""Tool results a device or runner turn shows in its chat answer though the launcher clips every result to 4 KB: the
platform keeps a diagram it made for the turn's MCP call in the chat session and attaches it to the turn's answer."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, Message, ToolCall, User

DIAGRAM_TOOLS = frozenset({"create_diagram", "edit_diagram"})
TURN_KEY = "device_turn_id"


async def caller_device_job(db: AsyncSession, caller: Any, user: User, workspace: str) -> DeviceJob | None:
    # The person's device or runner job behind the MCP connection's launcher session, if any.
    from ..mcp_workflow_run_session import _gateway

    gateway = await _gateway(db, caller, user, workspace) if workspace else None
    job_id = str(((gateway.metadata_ or {}) if gateway is not None else {}).get("device_job_id") or "")
    job = await db.get(DeviceJob, job_id) if job_id else None
    if job is None or job.owner_user_id != str(user.id) or job.workspace_id != workspace:
        return None
    return job


async def keep_turn_diagram(db: AsyncSession, *, caller: Any, user: User, workspace: str, tool_name: str,
                            result: Any) -> None:
    if tool_name not in DIAGRAM_TOOLS or not isinstance(result, dict) or not result.get("diagram_xml"):
        return
    job = await caller_device_job(db, caller, user, workspace)
    if job is None:
        return
    db.add(ToolCall(session_id=job.session_id, tool_name=tool_name, status="success", result=dict(result),
                    parameters={"title": str(result.get("title") or "")[:200], TURN_KEY: job.turn_id or ""}))
    await db.flush()


async def attach_turn_results(db: AsyncSession, job: DeviceJob, answer: Message) -> None:
    rows = (await db.execute(select(ToolCall).where(
        ToolCall.session_id == job.session_id, ToolCall.message_id.is_(None),
        ToolCall.tool_name.in_(DIAGRAM_TOOLS)))).scalars().all()
    for row in rows:
        if isinstance(row.parameters, dict) and row.parameters.get(TURN_KEY) == (job.turn_id or ""):
            row.message_id = answer.id


__all__ = ["DIAGRAM_TOOLS", "attach_turn_results", "caller_device_job", "keep_turn_diagram"]
