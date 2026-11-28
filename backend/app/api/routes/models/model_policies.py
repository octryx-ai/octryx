"""Model Policy registry API (``/api/v1/model-policies``)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.core.workspace_ref import WorkspaceId
from ....services.access_control import require_project_access
from ....services.auth import get_current_user
from ....services.model_policy import policies as model_policies
from ....services.model_policy.serialization import serialize_policy, serialize_policy_revision
from ....services.workspace_authorization import authorize_workspace
from ._model_policy_http import authorized_policy, refusals_as_http

router = APIRouter(prefix="/api/v1/model-policies", tags=["model-policies"])


class CreatePolicyRequest(BaseModel):
    workspace_id: WorkspaceId = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=120)
    entries: list[dict[str, Any]]


class SavePolicyDraftRequest(BaseModel):
    entries: list[dict[str, Any]]


class PublishPolicyRequest(BaseModel):
    governance_approval_id: str | None = Field(default=None, max_length=36)
    # The single-step publish under the ``single_admin`` approval rule: approve the own pending review first.
    self_approve: bool = False


@router.get("")
async def list_policies(
    workspace_id: str = Query(..., min_length=1, max_length=36),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    workspace = await authorize_workspace(
        db, current_user=current_user, workspace_id=workspace_id, require_author=False
    )
    rows = await model_policies.list_policies(db, workspace)
    return {"workspace_id": workspace, "items": [serialize_policy(row) for row in rows], "count": len(rows)}


@router.post("", status_code=201)
async def create_policy(
    body: CreatePolicyRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await require_project_access(db, current_user.id, body.workspace_id)
    workspace = await authorize_workspace(
        db, current_user=current_user, workspace_id=body.workspace_id, require_author=True
    )
    with refusals_as_http():
        policy, revision = await model_policies.create_policy(
            db, workspace_id=workspace, name=body.name, entries=body.entries, user=current_user
        )
    return {"policy": serialize_policy(policy), "revision": serialize_policy_revision(revision)}


@router.get("/{policy_id}")
async def get_policy(
    policy_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    policy = await authorized_policy(db, current_user, policy_id, author=False)
    return serialize_policy(policy, await model_policies.list_policy_revisions(db, policy))


@router.put("/{policy_id}/draft")
async def save_policy_draft(
    policy_id: str,
    body: SavePolicyDraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    policy = await authorized_policy(db, current_user, policy_id, author=True)
    with refusals_as_http():
        revision = await model_policies.save_policy_draft(db, policy=policy, entries=body.entries, user=current_user)
    return serialize_policy_revision(revision)


@router.post("/{policy_id}/retire")
async def retire_policy(
    policy_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    policy = await authorized_policy(db, current_user, policy_id, author=True)
    with refusals_as_http():
        await model_policies.retire_policy(db, policy=policy, user=current_user)
    return serialize_policy(policy, await model_policies.list_policy_revisions(db, policy))


async def _revision(db: AsyncSession, user: User, policy_id: str, revision: int, *, author: bool):
    policy = await authorized_policy(db, user, policy_id, author=author)
    with refusals_as_http():
        return policy, await model_policies.get_policy_revision(db, policy, revision)


@router.get("/{policy_id}/revisions/{revision}/admission")
async def policy_admission(
    policy_id: str, revision: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    policy, row = await _revision(db, current_user, policy_id, revision, author=False)
    admission = await model_policies.policy_admission(db, policy.workspace_id, row)
    return {"revision": row.revision, "admission": admission.as_dict()}


@router.post("/{policy_id}/revisions/{revision}/submit")
async def submit_policy_revision(
    policy_id: str, revision: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    policy, row = await _revision(db, current_user, policy_id, revision, author=True)
    with refusals_as_http():
        await model_policies.submit_policy_revision(db, policy=policy, revision=row, user=current_user)
    return serialize_policy_revision(row)


@router.post("/{policy_id}/revisions/{revision}/publish")
async def publish_policy_revision(
    policy_id: str,
    revision: int,
    body: PublishPolicyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    policy, row = await _revision(db, current_user, policy_id, revision, author=True)
    with refusals_as_http():
        gate = await model_policies.publish_policy_revision(
            db, policy=policy, revision=row, approval_id=body.governance_approval_id, user=current_user,
            self_approve=body.self_approve,
        )
    return {"revision": serialize_policy_revision(row), "approval_gate": gate}


@router.post("/{policy_id}/revisions/{revision}/retire")
async def retire_policy_revision(
    policy_id: str, revision: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    policy, row = await _revision(db, current_user, policy_id, revision, author=True)
    with refusals_as_http():
        await model_policies.retire_policy_revision(db, policy=policy, revision=row, user=current_user)
    return serialize_policy_revision(row)
