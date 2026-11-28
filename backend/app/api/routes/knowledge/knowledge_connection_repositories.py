"""Find a Bitbucket connection's repositories to register them as Knowledge repository sources."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.sources.connection_repositories import (
    PAGE_SIZE,
    default_branch,
    list_repositories,
    repository_connections,
    target_workspaces,
)
from ....services.knowledge.sources.sync.contract import ConnectorError
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/connections", tags=["workspace-knowledge"])


async def _author(db: AsyncSession, user: User, workspace_id: str) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=True)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


def _refusal(error: ConnectorError) -> HTTPException:
    return HTTPException(status_code=409, detail={"state": "refused", "reason": error.reason})


@router.get("")
async def list_repository_connections(
    workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    authorized = await _author(db, current_user, workspace_id)
    return {"connections": await repository_connections(db, authorized.project_id)}


@router.get("/{connection_id}/repositories")
async def list_connection_repositories(
    workspace_id: str,
    connection_id: str,
    q: str | None = Query(default=None, max_length=100),
    start: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=PAGE_SIZE, ge=1, le=PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _author(db, current_user, workspace_id)
    try:
        return await list_repositories(db, authorized.project_id, connection_id, q=q, start=start, limit=limit)
    except ConnectorError as error:
        raise _refusal(error) from None


@router.get("/{connection_id}/repositories/{project_key}/{slug}/default-branch")
async def connection_repository_default_branch(
    workspace_id: str,
    connection_id: str,
    project_key: str,
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _author(db, current_user, workspace_id)
    try:
        branch = await default_branch(db, authorized.project_id, connection_id, project_key, slug)
    except ConnectorError as error:
        raise _refusal(error) from None
    return {"default_branch": branch}


@router.get("/{connection_id}/workspaces")
async def connection_target_workspaces(
    workspace_id: str,
    connection_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _author(db, current_user, workspace_id)
    return {"workspaces": await target_workspaces(db, current_user.id, connection_id, authorized.project_id)}


__all__ = ["router"]
