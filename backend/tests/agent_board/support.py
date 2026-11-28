"""Shared seeds for the agent board tests."""

from __future__ import annotations

import uuid

from app.models import AgentPresence, User, WorkItem
from app.services.agent_board.identity import AgentIdentity, resolve_agent_identity
from app.services.mcp_work_access import WorkGrantScope, build_work_grant_scope
from app.time_utils import utc_now


async def seed_item(db, workspace_id: str, key: str = "BRD-1", *, title: str = "Fix login", epic: str | None = None):
    item = WorkItem(id=str(uuid.uuid4()), project_id=workspace_id, source_key=key, title=title, epic_key=epic)
    db.add(item)
    await db.flush()
    return item


async def seed_presence(db, user_id: str, workspace_id: str, *, work_item_key: str | None = None) -> str:
    session_key = str(uuid.uuid4())
    now = utc_now()
    db.add(AgentPresence(id=str(uuid.uuid4()), session_key=session_key, user_id=user_id, project_id=workspace_id,
                         profile="governed", client="octryx-claude", state="active", work_item_key=work_item_key,
                         device_key=user_id[:32],
                         registered_at=now, last_seen_at=now))
    await db.flush()
    return session_key


async def scope_for(db, user_id: str, *, grant_id: str | None = None) -> tuple[User, WorkGrantScope]:
    user = await db.get(User, user_id)
    return user, await build_work_grant_scope(db, user=user, grant_id=grant_id, binding=None)


async def agent(db, user_id: str, *, session_key: str | None = None, grant_id: str = "grant-a") -> AgentIdentity:
    headers = {"x-octryx-session": session_key} if session_key else {}
    return await resolve_agent_identity(db, user_id=user_id, grant_id=grant_id, headers=headers)
