"""Authorization policy for the Agent Definition revision API.

Single authorization owner for ``/api/v1/agent-definitions``, so
``app/api/routes/agent_definition_revisions.py`` can stay thin HTTP transport.
The semantics deliberately mirror
:mod:`app.services.workflow_definition_access`: an out-of-scope row raises the
same 404 as a missing row, and acting on a revision requires the project
``admin`` or ``owner`` role.

**Reads are not widened.** There is one role rule for the whole revision API,
reads included, because a revision body *is* the authored definition: system and
output prompts, per-step instructions, success criteria, and the tool allow-list.
Handing that to every project member would make this API a disclosure path that
the panel's own agent surface does not open. Listing revisions and reading one
therefore need the same ``admin``/``owner`` role as drafting and publishing.

``AgentDefinition.project_id`` is nullable, so exactly two scopes exist:

* **Project scope** (``project_id`` set) — the caller needs a project role at all
  to learn the definition exists (otherwise 404), and the ``admin`` or ``owner``
  role to list, read, draft, validate, publish, or restore a revision (otherwise
  403). Membership and roles come from :mod:`app.services.access_control`, which
  lets global admins through.
* **Owner scope** (``project_id`` is ``NULL``) — a definition that has not been
  assigned to a Workspace. It is private authoring state, so it is visible only
  to its ``owner_id`` and to global admins. This is intentionally narrower than
  the workflow module's platform scope: an unassigned agent definition is not a
  platform-wide policy object.

The two failure modes are kept distinct on purpose: 404 when the caller cannot
see the Workspace at all (so the API never confirms that another Workspace or
another user owns a given id), and 403 only for a caller who can already read the
Workspace but lacks the author role — which discloses nothing new.
"""

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
    """Return the definition, authorized for the revision API.

    Raises 404 when the definition is missing or the caller cannot see its
    Workspace, and 403 when the caller can read the Workspace but lacks the
    author role.
    """
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
    """Return a revision plus its definition, authorized for the revision API.

    Same two failure modes as :func:`resolve_definition`, reported with the
    revision's own not-found detail so an out-of-scope revision id and an unknown
    revision id are indistinguishable.
    """
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
    """Authorize any revision-API action on an existing *definition*.

    Raises 404 (``not_found_detail``) when the row lies outside the caller's
    scope, so an out-of-scope row is indistinguishable from a missing one.
    Raises 403 only when the caller may already read the Workspace but lacks the
    author role, which discloses nothing new.
    """
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
    """Authorize the Workspace a restore would move the definition into.

    A snapshot carries the ``project_id`` the definition had when it was taken.
    Restoring it writes that value back onto the live row, so a caller authorized
    only in the definition's *current* scope could otherwise move it into another
    Workspace — or out of one into private owner scope — without any authority
    there. ``project_id`` is therefore re-authorized as a target, never accepted
    from the snapshot as authority.

    Raises 403 rather than 404: the caller is already authorized to read this
    revision, so the target id is not new information to them.
    """
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
