"""Knowledge › Sources settings of a Workspace: the source ACL switch and the Custom REST source catalog.

Under ``/api/v1/workspaces/{workspace_id}/knowledge``:

- ``GET  source-acl``: whether the Workspace enforces source ACLs and how many withheld restricted items switching
  it on would let in (a count only). Platform admin.
- ``PUT  source-acl`` ``{enforce, reason, dry_run?}``: change it (audited with actor, Workspace, old/new, reason
  and that count); ``dry_run`` answers the same without changing or recording anything. Platform admin.
- ``GET  rest-sources``: the Custom REST definitions and read operations usable as a Knowledge source here, without
  Secure Work access and without any credential (``sources/sync/rest_discovery``). A Workspace owner/admin sees
  what their Workspace can reach; a platform admin sees every definition.

Why: the first Custom REST source dry-ran fine and then withheld every item because
the Workspace did not enforce source ACLs and nothing could turn that on; and its setup drawer read REST APIs through
the Work intake's discovery, which a Workspace owner without Secure Work access cannot open.

Refusals as elsewhere in Knowledge (``access/authorization``): an unknown or foreign Workspace is one 404; a caller
who can read the Workspace but lacks the role is 403 with a code and a message.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.auth import get_current_user
from ...services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.knowledge.sources.sync.acl_switch import enforcement_state, set_enforcement
from ...services.knowledge.sources.sync.rest_discovery import rest_source_catalog
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge", tags=["workspace-knowledge"])

ACL_SWITCH_ADMIN_ONLY = {"code": "source_acl_enforce_admin_only",
                         "message": "Only a platform admin can change whether this Workspace enforces source ACLs."}


class EnforceBody(BaseModel):
    enforce: bool
    reason: str
    dry_run: bool = False

    @field_validator("reason")
    @classmethod
    def _reason_given(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A reason is required.")
        return value.strip()


async def _workspace(db: AsyncSession, user: User, workspace_id: str, *, author: bool) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=author)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


async def _platform_admin_workspace(db: AsyncSession, user: User, workspace_id: str) -> AuthorizedWorkspace:
    """The Workspace first (404 for unknown and foreign alike), then the platform admin role (403)."""
    authorized = await _workspace(db, user, workspace_id, author=False)
    if not await is_global_admin(db, user.id):
        raise HTTPException(status_code=403, detail=ACL_SWITCH_ADMIN_ONLY)
    return authorized


@router.get("/source-acl")
async def get_source_acl(
    workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    authorized = await _platform_admin_workspace(db, current_user, workspace_id)
    return await enforcement_state(db, authorized.project_id)


@router.put("/source-acl")
async def put_source_acl(
    workspace_id: str,
    body: EnforceBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _platform_admin_workspace(db, current_user, workspace_id)
    return await set_enforcement(db, project_id=authorized.project_id, enforce=body.enforce, reason=body.reason,
                                 actor_id=current_user.id, dry_run=body.dry_run)


@router.get("/rest-sources")
async def get_rest_source_catalog(
    workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """What a ``custom_rest`` source of this Workspace can read (Workspace owner/admin, or a platform admin)."""
    authorized = await _workspace(db, current_user, workspace_id, author=True)
    return await rest_source_catalog(db, authorized.project_id,
                                     platform_admin=await is_global_admin(db, current_user.id))
