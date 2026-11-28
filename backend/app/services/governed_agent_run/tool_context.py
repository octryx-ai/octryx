"""The governed tool context of a governed agent run."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Role, Session, UserRole
from ...tools.context import ToolContext
from ..access_control import get_project_role_for_user
from ..project import get_project_config
from ..run_capability.declared import capability_from_run_profile
from ..session.workspace import get_session_workspace_root
from ..workspace_root_service import resolve_app_workspace_root
from .context import ExecutionContext

_DEFAULT_ROLES = ["viewer"]


async def build_run_tool_context(db: AsyncSession, context: ExecutionContext) -> ToolContext:
    workspace = context.workspace_id
    roles = [
        str(name)
        for name in (
            await db.execute(
                select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == context.user_id)
            )
        ).scalars()
    ] or list(_DEFAULT_ROLES)
    project_config = {
        **(await get_project_config(workspace, db)),
        "project_id": workspace,
        "project_role": await get_project_role_for_user(db, context.user_id, workspace) or "",
        "user_roles": roles,
        "workspace_root": str(resolve_app_workspace_root()),
    }
    session_root = await get_session_workspace_root(db, context.session_id)
    session = await db.get(Session, context.session_id)
    # The run dispatches under the class its session was admitted with.
    execution_profile = (session.metadata_ or {}).get("execution_profile") if session is not None else None
    return ToolContext(
        user_id=context.user_id,
        project_ids=[workspace],
        roles=roles,
        session_id=context.session_id,
        project_config=project_config,
        db=db,
        workspace_root=str(session_root),
        run_capability=capability_from_run_profile(execution_profile).tool_context_state(),
    )


__all__ = ["build_run_tool_context"]
