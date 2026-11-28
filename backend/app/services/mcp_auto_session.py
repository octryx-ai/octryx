"""Zero-config platform sessions for MCP clients."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session, ToolCall, User
from ..time_utils import utc_now

logger = logging.getLogger(__name__)

AUTO_SESSION_SOURCE = "mcp_auto_tracked"
_MAX_PARAM_CHARS = 600


def mcp_client_name(ctx: Any) -> str:
    try:
        client_params = ctx.session.client_params  # type: ignore[union-attr]
        info = getattr(client_params, "clientInfo", None) or getattr(client_params, "client_info", None)
        name = str(getattr(info, "name", "") or "").strip()
        version = str(getattr(info, "version", "") or "").strip()
        if name:
            return f"{name} {version}".strip()
    except (AttributeError, TypeError):
        pass
    return "mcp-client"


async def record_mcp_tool_activity(
    db: AsyncSession,
    *,
    user: User,
    grant_id: str | None,
    client_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    activity_date = utc_now().date().isoformat()
    session = (
        await db.execute(
            select(Session)
            .where(
                Session.agent_type == "external_agent",
                Session.metadata_["external_source"].as_string() == AUTO_SESSION_SOURCE,
                Session.metadata_["oauth_grant_id"].as_string() == str(grant_id or ""),
                Session.metadata_["activity_date"].as_string() == activity_date,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if session is None:
        session = Session(
            id=str(uuid.uuid4()),
            user_id=user.id,
            agent_type="external_agent",
            status="active",
            origin="mcp",
            metadata_={
                "external_source": AUTO_SESSION_SOURCE,
                "oauth_grant_id": str(grant_id or ""),
                "activity_date": activity_date,
                "mcp_client": client_name,
                "summary": f"MCP activity of {client_name} on {activity_date} (auto-tracked, zero config).",
            },
        )
        db.add(session)
        await db.flush()
        logger.info("mcp_auto_session_created client=%s date=%s", client_name, activity_date)
    compact_params = json.dumps(arguments, ensure_ascii=False, default=str)
    if len(compact_params) > _MAX_PARAM_CHARS:
        compact_params = compact_params[:_MAX_PARAM_CHARS] + "..."
    db.add(
        ToolCall(
            session_id=session.id,
            tool_name=tool_name,
            parameters={"compact": compact_params, "client": client_name},
            result={"status": "ok"},
            status="success",
        )
    )
    await db.flush()
    return session.id


__all__ = ["mcp_client_name", "record_mcp_tool_activity"]
