"""Authorization policy for the Agent Definition revision API. An out-of-scope row raises the same 404 as a missing
row."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentDefinition, AgentDefinitionRevision, User
from .access_control import get_project_role_for_user
from .admin.governance.admin_access_service import is_global_admin
from .agent_definition_snapshot import snapshot_header

DEFINITION_NOT_FOUND_DETAIL = "Agent definition not found"
REVISION_NOT_FOUND_DETAIL = "Agent definition revision not found"

#: Project roles allowed to list, read, draft, validate, publish, or restore a
#: revision. One set for the whole API: a revision body is authored content.
AUTHOR_PROJECT_ROLES = frozenset({"admin", "owner"})


async def resolve_definition(
    db: AsyncSession, *, current_user: User, definition_id: str
) -> AgentDefinition:
    resolved_id = str(definition_id or "").strip()
    definition = (
        (
            await db.execute(
                select(AgentDefinition).where(AgentDefinition.id == resolved_id)
            )
        ).scalar_one_or_none()
        if resolved_id
        else None
    )
    if definition is None:
        raise HTTPException(status_code=404, detail=DEFINITION_NOT_FOUND_DETAIL)
    await authorize_definition(
        db,
        current_user=current_user,
        definition=definition,
        not_found_detail=DEFINITION_NOT_FOUND_DETAIL,
    )
    return definition


async def resolve_revision(
    db: AsyncSession, *, current_user: User, revision_id: str
) -> tuple[AgentDefinitionRevision, AgentDefinition]:
    # The revision's own not-found detail: an out-of-scope and an unknown revision id are indistinguishable.
    resolved_id = str(revision_id or "").strip()
    revision = (
        (
            await db.execute(
                select(AgentDefinitionRevision).where(
                    AgentDefinitionRevision.id == resolved_id
                )
            )
        ).scalar_one_or_none()
        if resolved_id
        else None
    )
    definition = (
        await db.get(AgentDefinition, revision.definition_id) if revision else None
    )
    if revision is None or definition is None:
        raise HTTPException(status_code=404, detail=REVISION_NOT_FOUND_DETAIL)
    await authorize_definition(
        db,
        current_user=current_user,
        definition=definition,
        not_found_detail=REVISION_NOT_FOUND_DETAIL,
    )
    return revision, definition


async def authorize_definition(
    db: AsyncSession,
    *,
    current_user: User,
    definition: AgentDefinition,
    not_found_detail: str,
) -> None:
    # 404 outside the caller's scope, like a missing row; 403 only when the Workspace is already readable.
    project_id = str(definition.project_id or "").strip() or None
    if project_id is None:
        # Owner scope: private authoring state. Global admins retain access so
        # platform administration keeps working, but no other user learns that
        # this definition id exists.
        if definition.owner_id == current_user.id:
            return
        if await is_global_admin(db, current_user.id):
            return
        raise HTTPException(status_code=404, detail=not_found_detail)

    role = await get_project_role_for_user(db, current_user.id, project_id)
    if role is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    # Reads need the author role too: a revision exposes system prompts, step instructions and tool allowlists.
    if role not in AUTHOR_PROJECT_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Project admin or owner role required for this action.",
        )


async def authorize_restore_target_scope(
    db: AsyncSession,
    *,
    current_user: User,
    definition: AgentDefinition,
    revision: AgentDefinitionRevision,
) -> None:
    # The snapshot's ``project_id`` is re-authorized as a target, never taken as authority: a restore could otherwise
    # move the definition into a Workspace the caller has no authority in.
    target_project_id = (
        str(snapshot_header(revision.snapshot).get("project_id") or "").strip() or None
    )
    current_project_id = str(definition.project_id or "").strip() or None
    if target_project_id == current_project_id:
        return

    if target_project_id is None:
        # Moving into owner scope makes the definition private to its owner.
        if definition.owner_id == current_user.id or await is_global_admin(
            db, current_user.id
        ):
            return
        raise HTTPException(
            status_code=403,
            detail="Definition owner or global admin required to unassign the Workspace.",
        )

    role = await get_project_role_for_user(db, current_user.id, target_project_id)
    if role is None or role not in AUTHOR_PROJECT_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Project admin or owner role required in the target Workspace.",
        )


__all__ = [
    "AUTHOR_PROJECT_ROLES",
    "DEFINITION_NOT_FOUND_DETAIL",
    "REVISION_NOT_FOUND_DETAIL",
    "authorize_definition",
    "authorize_restore_target_scope",
    "resolve_definition",
    "resolve_revision",
]
