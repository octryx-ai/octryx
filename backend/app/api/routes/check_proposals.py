"""Proposed checks of a Workspace (From Correction to Check). Transport only.

Members read; approving, changing, rejecting and switching need the
approver permission (default: the Workspace owner or an admin, ``authorize_workspace(require_author=True)``). The
answers come from the proposal store (``check_proposals.store``) or, while ``settings.check_proposals_stub``
is on, from fixtures (``check_proposals.stub``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import AuditLog, User
from app.services.auth import get_current_user
from app.services.check_proposals import store, stub
from app.services.check_proposals.rules import CheckProposalRefusedError, reason_refusal
from app.services.knowledge.access.authorization import WorkspaceWriteForbiddenError, authorize_workspace
from app.services.knowledge.ledger.errors import EvidenceLedgerError

from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/check-proposals", tags=["check-proposals"])


class EditRequest(BaseModel):
    draft: dict[str, Any] | None = None
    message: dict[str, str] | None = None
    severity: str | None = Field(default=None, max_length=10)


class ApproveRequest(BaseModel):
    accept_unproven: bool = False
    note: str = Field(default="", max_length=500)


class ReasonRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class EnabledRequest(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=500)


async def _member(db: AsyncSession, user: User, workspace_id: str) -> None:
    try:
        await authorize_workspace(db, current_user=user, workspace_id=workspace_id)
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


async def _may_approve(db: AsyncSession, user: User, workspace_id: str) -> bool:
    try:
        await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=True)
    except (WorkspaceWriteForbiddenError, EvidenceLedgerError):
        return False
    return True


def _http(error: CheckProposalRefusedError) -> HTTPException:
    return HTTPException(error.status, {"code": error.code, "message": error.message})


async def _audit(db: AsyncSession, user: User, workspace_id: str, row: dict[str, Any], action: str,
                 **said: Any) -> dict[str, Any]:
    """The decision in the audit log, with what the person said (note, reason) and whether it was without proof."""
    details = {"workspace_id": workspace_id, "state": row["state"], "stub": stub.enabled(),
               **{key: value for key, value in said.items() if value not in (None, "")}}
    db.add(AuditLog(user_id=user.id, action=f"check_proposal.{action}", resource_type="check_proposal",
                    resource_id=row["id"], details=details))
    await db.commit()
    return row


@router.get("")
async def list_proposals(workspace_id: str, state: str = "", user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(db, user, workspace_id)
    states = {part.strip() for part in state.split(",") if part.strip()} or None
    found = stub.list_proposals(workspace_id, states) if stub.enabled() else await store.list_proposals(
        db, workspace_id, states)
    return {**found, "may_approve": await _may_approve(db, user, workspace_id)}


@router.get("/settings")
async def get_settings(workspace_id: str, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(db, user, workspace_id)
    return stub.workspace_settings() if stub.enabled() else await store.workspace_settings(db, workspace_id)


@router.get("/{proposal_id}")
async def get_proposal(workspace_id: str, proposal_id: str, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(db, user, workspace_id)
    try:
        return stub.get(workspace_id, proposal_id) if stub.enabled() else await store.get(db, workspace_id,
                                                                                            proposal_id)
    except CheckProposalRefusedError as error:
        raise _http(error) from None


@router.post("/{proposal_id}/edit")
async def edit_proposal(workspace_id: str, proposal_id: str, body: EditRequest,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(db, user, workspace_id)
    if not await _may_approve(db, user, workspace_id):
        raise _http(CheckProposalRefusedError("approver_permission_missing",
                                              "Ask the Workspace owner to change this check.", 403))
    try:
        changes = body.model_dump(exclude_none=True)
        row = stub.edit(workspace_id, proposal_id, user_id=user.id, body=changes) if stub.enabled() else \
            await store.edit(db, workspace_id, proposal_id, user_id=user.id, body=changes)
    except CheckProposalRefusedError as error:
        raise _http(error) from None
    return await _audit(db, user, workspace_id, row, "edited")


@router.post("/{proposal_id}/approve")
async def approve_proposal(workspace_id: str, proposal_id: str, body: ApproveRequest,
                           user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(db, user, workspace_id)
    if body.accept_unproven and (missing := reason_refusal(body.note)):
        # A check without proof is the risky case: whoever approves it says why.
        raise _http(CheckProposalRefusedError(missing.code, "Say why you approve this check without proof, in 1 to "
                                              "500 characters.", 422))
    try:
        decide = {"user_id": user.id, "may_approve": await _may_approve(db, user, workspace_id),
                  "accept_unproven": body.accept_unproven, "note": body.note}
        row = stub.approve(workspace_id, proposal_id, **decide) if stub.enabled() else \
            await store.approve(db, workspace_id, proposal_id, **decide)
    except CheckProposalRefusedError as error:
        raise _http(error) from None
    return await _audit(db, user, workspace_id, row, "approved", accept_unproven=body.accept_unproven or None,
                        note=body.note.strip())


@router.post("/{proposal_id}/reject")
async def reject_proposal(workspace_id: str, proposal_id: str, body: ReasonRequest,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(db, user, workspace_id)
    try:
        decide = {"user_id": user.id, "may_approve": await _may_approve(db, user, workspace_id), "reason": body.reason}
        row = stub.reject(workspace_id, proposal_id, **decide) if stub.enabled() else \
            await store.reject(db, workspace_id, proposal_id, **decide)
    except CheckProposalRefusedError as error:
        raise _http(error) from None
    return await _audit(db, user, workspace_id, row, "rejected", reason=body.reason.strip())


@router.post("/{proposal_id}/enabled")
async def switch_proposal(workspace_id: str, proposal_id: str, body: EnabledRequest,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _member(db, user, workspace_id)
    try:
        decide = {"may_approve": await _may_approve(db, user, workspace_id), "value": body.enabled,
                  "reason": body.reason}
        row = stub.set_enabled(workspace_id, proposal_id, **decide) if stub.enabled() else \
            await store.set_enabled(db, workspace_id, proposal_id, user_id=user.id, **decide)
    except CheckProposalRefusedError as error:
        raise _http(error) from None
    return await _audit(db, user, workspace_id, row, "switched", enabled=body.enabled, reason=body.reason.strip())
