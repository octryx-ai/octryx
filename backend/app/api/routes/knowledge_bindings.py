"""Read bindings between Knowledge Workspaces.

Thin: authenticate, authorize, delegate to ``services/knowledge/access/bindings``, map fixed reasons.
Listing needs Workspace access. Binding needs the authoring role in the reading Workspace *and* in
the source Workspace. Revoking needs the authoring role on either side.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ...services.knowledge.access.bindings import (
    BindingRefusedError,
    bindings_of,
    create_binding,
    resolve_scope,
    revoke_binding,
)
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/bindings", tags=["workspace-knowledge"])

REFUSALS = {
    "reader_author_required": (403, "Admin or owner role in this Workspace is required."),
    "author_required": (403, "Admin or owner role in this Workspace is required."),
    "self_binding": (422, "A Workspace cannot be bound to itself."),
    "invalid_products": (422, "The products are not valid product keys."),
    "classification_above_reader": (
        409,
        "The source Workspace's data classification is above this Workspace's; its knowledge may not flow here.",
    ),
    "classification_unresolved": (
        409,
        "Both Workspaces need a data classification before one may read the other.",
    ),
    "too_many_bindings": (409, "This Workspace already reads the maximum number of Workspaces."),
}


class BindingRequest(BaseModel):
    source_workspace_id: str = Field(min_length=1, max_length=64)
    products: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(default="", max_length=500)


async def _authorized(db, user, workspace_id: str, *, author: bool) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=author)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


def _refused(error: BindingRefusedError) -> HTTPException:
    status, detail = REFUSALS.get(error.reason, (422, "The binding was refused."))
    return HTTPException(status_code=status, detail=detail)


def _entry(row, *, other: str, names: dict[str, str], effective: str, inert_reason: str | None = None) -> dict:
    return {
        "id": row.id,
        "workspace_id": other,
        "workspace_name": names.get(other, ""),
        "products": list(row.products or []),
        "state": row.state,
        # "inert": the binding is active but not read right now, for ``inert_reason``.
        "effective": effective,
        "inert_reason": inert_reason,
        "reason": row.reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


async def _overview(db, authorized: AuthorizedWorkspace) -> dict:
    reads_from, read_by, names = await bindings_of(db, authorized.project_id)
    scope = await resolve_scope(db, authorized)
    readable = {source.authorized.project_id for source in scope.sources}

    def own_read(row) -> dict:
        if row.state != "active":
            return _entry(row, other=row.source_project_id, names=names, effective="revoked")
        if row.source_project_id in readable:
            return _entry(row, other=row.source_project_id, names=names, effective="active")
        reason = scope.skipped.get(row.source_project_id, "beyond_binding_limit")
        return _entry(row, other=row.source_project_id, names=names, effective="inert", inert_reason=reason)

    return {
        "workspace_id": authorized.project_id,
        "may_author": authorized.may_author,
        "reads_from": [own_read(row) for row in reads_from],
        "read_by": [_entry(row, other=row.reader_project_id, names=names, effective=row.state) for row in read_by],
    }


@router.get("")
async def list_bindings(
    workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return await _overview(db, await _authorized(db, current_user, workspace_id, author=False))


@router.post("")
async def bind_workspace(
    workspace_id: str,
    body: BindingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Let this Workspace read the source Workspace's knowledge (optionally only some products)."""
    reader = await _authorized(db, current_user, workspace_id, author=True)
    try:
        await create_binding(
            db,
            reader=reader,
            source_workspace_id=body.source_workspace_id,
            products=body.products,
            reason=body.reason,
            user=current_user,
        )
    except BindingRefusedError as error:
        raise _refused(error) from None
    except WorkspaceWriteForbiddenError:
        raise HTTPException(
            status_code=403, detail="Admin or owner role in the source Workspace is required."
        ) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    await db.commit()
    return await _overview(db, reader)


@router.delete("/{binding_id}")
async def unbind_workspace(
    workspace_id: str,
    binding_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=False)
    try:
        binding = await revoke_binding(db, workspace=authorized, binding_id=binding_id, user=current_user)
    except BindingRefusedError as error:
        raise _refused(error) from None
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found.")
    await db.commit()
    return await _overview(db, authorized)
