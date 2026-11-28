"""Workspace repository sources: the local-snapshot policy and the platform source viewer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    authorize_workspace,
)
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.sources.repository_snapshot.label_config import set_repository_labels
from ....services.knowledge.sources.repository_snapshot.labels import RepositoryLabelError
from ....services.knowledge.sources.repository_snapshot.policy import (
    local_snapshots_allowed,
    set_local_snapshots_allowed,
)
from ....services.knowledge.sources.repository_snapshot.viewer import (
    STATE_BLOB_SUPERSEDED,
    BlobSuperseded,
    view_repository_file,
)
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/repositories", tags=["workspace-knowledge"])

FILE_NOT_FOUND_DETAIL = "Repository file not found at this commit"


class RepositoryPolicyRequest(BaseModel):
    allow_local_snapshots: bool


class RepositoryLabelRequest(BaseModel):
    name: str | None = None
    version: str | None = None


async def _authorized(db: AsyncSession, user: User, workspace_id: str) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id)
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


async def _policy(db: AsyncSession, authorized: AuthorizedWorkspace) -> dict:
    return {
        "workspace_id": authorized.project_id,
        "may_author": authorized.may_author,
        "allow_local_snapshots": await local_snapshots_allowed(db, authorized.project_id),
    }


@router.get("/policy")
async def get_repository_policy(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _policy(db, await _authorized(db, current_user, workspace_id))


@router.put("/policy")
async def set_repository_policy(
    workspace_id: str,
    body: RepositoryPolicyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id)
    if not authorized.may_author:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL)
    await set_local_snapshots_allowed(
        db, authorized.project_id, allowed=body.allow_local_snapshots, actor_id=str(current_user.id)
    )
    await db.commit()
    return await _policy(db, authorized)


@router.put("/{connector_key}/label")
async def set_repository_label(
    workspace_id: str,
    connector_key: str,
    body: RepositoryLabelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id)
    if not authorized.may_author:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL)
    try:
        labelled = await set_repository_labels(
            db, project_id=authorized.project_id, connector_key=connector_key[:40], name=body.name,
            version=body.version, actor_id=str(current_user.id),
        )
    except RepositoryLabelError as error:
        raise HTTPException(status_code=422, detail={"state": "invalid_request", "reason": error.reason}) from None
    if labelled is None:
        raise HTTPException(status_code=404, detail="Repository source not found")
    await db.commit()
    return {"workspace_id": authorized.project_id, **labelled}


@router.get("/{connector_key}/blob/{commit}/{path:path}")
async def view_repository_blob(
    workspace_id: str,
    connector_key: str,
    commit: str,
    path: str,
    blob: str | None = Query(default=None, max_length=40),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id)
    view = await view_repository_file(
        db, authorized, connector_key=connector_key[:40], commit=commit[:40], path=path[:1024], blob_sha=blob
    )
    if view is None:
        raise HTTPException(status_code=404, detail=FILE_NOT_FOUND_DETAIL)
    if isinstance(view, BlobSuperseded):
        # A bare commit the index no longer resolves for this path: say so and name the current one.
        raise HTTPException(
            status_code=404,
            detail={"state": STATE_BLOB_SUPERSEDED, "path": view.path, "current_commit": view.current_commit},
        )
    return {
        "workspace_id": authorized.project_id,
        "connector_key": connector_key,
        "path": view.path,
        "commit": view.commit,
        "blob_sha": view.blob_sha,
        "language": view.language,
        "source_id": view.source_id,
        "revision_id": view.revision_id,
        "current": view.current,
        "spans": [{"ordinal": ordinal, "text": text} for ordinal, text in view.spans],
    }
