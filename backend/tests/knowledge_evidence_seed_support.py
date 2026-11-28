"""Database seeding for the Workspace Knowledge Evidence tests: Workspaces, members, outsiders and tool contexts."""

from __future__ import annotations

import uuid

from app.tools.context import ToolContext


def new_workspace_id() -> str:
    return str(uuid.uuid4())


async def seed_workspace(db, *, name: str | None = None) -> str:
    from app.models import Project

    workspace_id = new_workspace_id()
    db.add(
        Project(
            id=workspace_id,
            name=name or f"ws-{workspace_id[:8]}",
            config={},
            is_active=True,
        )
    )
    await db.flush()
    return workspace_id


async def seed_member(db, *, workspace_id: str, role: str = "admin", username: str | None = None) -> str:
    from app.models import User
    from app.models.security.user import UserProject

    user_id = new_workspace_id()
    handle = username or f"member{user_id[:8]}"
    db.add(
        User(
            id=user_id,
            username=handle,
            email=f"{handle}@example.com",
            password_hash="x",
            is_active=True,
        )
    )
    await db.flush()
    db.add(UserProject(user_id=user_id, project_id=workspace_id, role=role))
    await db.flush()
    return user_id


async def seed_outsider(db, *, username: str | None = None) -> str:
    from app.models import User

    user_id = new_workspace_id()
    handle = username or f"outsider{user_id[:8]}"
    db.add(
        User(
            id=user_id,
            username=handle,
            email=f"{handle}@example.com",
            password_hash="x",
            is_active=True,
        )
    )
    await db.flush()
    return user_id


async def fetch_user(db, user_id: str):
    from app.models import User

    return await db.get(User, user_id)


def tool_context(*, user_id: str, project_id: str | None, project_ids: list[str], db) -> ToolContext:
    return ToolContext(
        user_id=user_id,
        project_ids=project_ids,
        roles=[],
        session_id=new_workspace_id(),
        project_config={"project_id": project_id} if project_id else {},
        db=db,
    )
