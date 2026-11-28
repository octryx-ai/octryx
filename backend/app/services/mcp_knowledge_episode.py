"""``episode_summary`` on the Knowledge MCP: an external CLI session returns what it learned. Written as a governed
source revision of the Workspace Knowledge."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session, User
from .knowledge.access.authorization import authorize_tool_workspace
from .knowledge.episodes.writer import EpisodeProvenance, episode_refusal, record_episode_summary, refusal
from .knowledge.ledger.errors import EvidenceLedgerError
from .mcp_auto_session import record_mcp_tool_activity
from .mcp_external_session import EXTERNAL_AGENT_TYPE, create_external_shadow_session
from .mcp_governed_knowledge import WRITE_SCOPE, McpCaller, failure, resolve_mcp_workspace
from .mcp_knowledge_observability import audit_mcp_knowledge_tool_call, enforce_mcp_knowledge_rate_limit

TOOL_NAME = "episode_summary"
# The CLI's own session id: a bounded token, validated as data, never interpreted.
_CLIENT_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


async def _shadow_session(db: AsyncSession, *, user: User, caller: McpCaller, workspace: str, client_session_id: str):
    existing = (
        await db.execute(
            select(Session)
            .where(
                Session.user_id == user.id,
                Session.agent_type == EXTERNAL_AGENT_TYPE,
                Session.metadata_["client_session_id"].as_string() == client_session_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    return await create_external_shadow_session(
        db,
        user=user,
        project_id=workspace,
        grant_id=caller.grant_id,
        client=caller.client_name,
        source_metadata={"client_session_id": client_session_id},
    )


async def _record(
    db: AsyncSession, *, user: User, caller: McpCaller, workspace: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    try:
        authorized = await authorize_tool_workspace(
            db, user_id=str(user.id), project_id=workspace, allowed_project_ids=[workspace]
        )
    except EvidenceLedgerError:
        return failure("not_found")
    refused = await episode_refusal(db, authorized, arguments.get("summary"))
    if refused is not None:
        return refused
    client_session_id = arguments.get("client_session_id")
    if type(client_session_id) is not str or not _CLIENT_SESSION_ID.fullmatch(client_session_id):
        return refusal("invalid_session")
    session = await _shadow_session(
        db, user=user, caller=caller, workspace=workspace, client_session_id=client_session_id
    )
    provenance = EpisodeProvenance(
        session_id=str(session.id),
        client=caller.client_name,
        recorded_by=str(user.id),
        session_date=(session.started_at.date().isoformat() if session.started_at else ""),
    )
    return await record_episode_summary(
        db,
        authorized=authorized,
        provenance=provenance,
        summary=arguments.get("summary"),
        title=arguments.get("title"),
        products=arguments.get("products"),
        version=arguments.get("version"),
    )


async def run_episode_summary(db: AsyncSession, *, caller: McpCaller, arguments: dict[str, Any]) -> dict[str, Any]:
    if WRITE_SCOPE not in caller.scopes:
        return failure("scope_required")
    user = await db.get(User, caller.user_id)
    if user is None or not user.is_active:
        return failure("user_inactive")
    await enforce_mcp_knowledge_rate_limit(api_key_id=caller.grant_id, user_id=caller.user_id, tool_name=TOOL_NAME)
    workspace = resolve_mcp_workspace(caller)
    await record_mcp_tool_activity(
        db,
        user=user,
        grant_id=caller.grant_id,
        client_name=caller.client_name,
        tool_name=TOOL_NAME,
        arguments={"argument_names": sorted(str(key) for key in arguments)},
    )
    if isinstance(workspace, dict):
        result: dict[str, Any] = workspace
    else:
        result = await _record(db, user=user, caller=caller, workspace=workspace, arguments=arguments)
    state = str(result.get("state") or "error")
    await audit_mcp_knowledge_tool_call(
        db,
        user_id=str(user.id),
        api_key_id=caller.grant_id,
        api_key_project_id=",".join(caller.bound_project_ids) or None,
        tool_name=TOOL_NAME,
        arguments={"project_id": workspace if isinstance(workspace, str) else ""},
        result={"state": state},
        status_value="success" if state in {"recorded", "duplicate"} else state,
        transport="mcp",
    )
    return result


__all__ = ["TOOL_NAME", "run_episode_summary"]
