"""Settings → Workspace → Repositories. Transport only.

- ``GET /api/v1/workspaces/{workspace_id}/repositories``: the Workspace's repository records with their source,
  default branch, owners and coding setup summary (members);
- ``GET …/{repository_id}/coding-setup``: the record's coding setup (members; secret references masked);
- ``PUT …/{repository_id}/coding-setup``: save it (Workspace owner or admin; audited);
- ``GET …/connections``: the Workspace's GitHub, GitLab and Bitbucket connections a run repository can use (members);
- ``POST …/detect``: through one of them, whether a repository exists and which apps it holds (owner or admin);
- ``POST …``: add it as a repository for runs (owner or admin; audited), see ``repositories/run_repository.py``;
- ``GET …/sources``: the Workspace's Knowledge git sources a record can be created from (owner or admin);
- ``POST …/from-source``: create the record from one of them, its URL and branch read from the source (owner or admin;
  audited), see ``repositories/knowledge_source.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import AuditLog, User
from app.services.auth import get_current_user
from app.services.knowledge.access.authorization import (
    AuthorizedWorkspace,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from app.services.knowledge.ledger.errors import EvidenceLedgerError
from app.services.secure_work.access import work_scope_project_ids
from app.services.secure_work.repositories import knowledge_source, run_repository
from app.services.secure_work.repositories.record import (
    describe_repository,
    read_setup,
    save_setup,
    workspace_repositories,
    workspace_repository,
)

from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/repositories", tags=["workspace-repositories"])


async def _authorize(db: AsyncSession, user: User, workspace_id: str, *, author: bool = False) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=author)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(403, "Workspace owner or admin role required") from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


@router.get("")
async def list_repositories(
    workspace_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize(db, user, workspace_id)
    return {"items": await workspace_repositories(db, workspace_id)}


@router.get("/connections")
async def list_run_connections(
    workspace_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize(db, user, workspace_id)
    return {"items": await run_repository.connections(db, workspace_id)}


@router.post("/detect")
async def detect_run_repository(
    workspace_id: str, payload: dict[str, Any], user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize(db, user, workspace_id, author=True)
    return await run_repository.detect(db, workspace_id, payload)


@router.post("", status_code=201)
async def add_run_repository(
    workspace_id: str, payload: dict[str, Any], user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize(db, user, workspace_id, author=True)
    repo = await run_repository.add(db, user=user, workspace_id=workspace_id, body=payload)
    return describe_repository(repo, {})


@router.get("/sources")
async def list_repository_sources(
    workspace_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    authorized = await _authorize(db, user, workspace_id, author=True)
    return await knowledge_source.source_catalog(db, authorized)


class SourceBinding(BaseModel):
    connector_id: str = Field(min_length=36, max_length=36, pattern="^[a-f0-9-]+$")


@router.post("/from-source")
async def add_repository_from_source(
    workspace_id: str, body: SourceBinding, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    authorized = await _authorize(db, user, workspace_id, author=True)
    return await knowledge_source.bind_source(db, authorized, user.id, body.connector_id)


@router.get("/{repository_id}/coding-setup")
async def get_coding_setup(
    workspace_id: str, repository_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize(db, user, workspace_id)
    repo = await workspace_repository(db, workspace_id, repository_id)
    return await read_setup(db, repo, scope=await work_scope_project_ids(db, user))


@router.put("/{repository_id}/coding-setup")
async def put_coding_setup(
    workspace_id: str, repository_id: str, payload: dict[str, Any],
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize(db, user, workspace_id, author=True)
    repo = await workspace_repository(db, workspace_id, repository_id)
    saved = await save_setup(db, user=user, repo=repo, payload=payload)
    db.add(AuditLog(user_id=user.id, action="code_repository.coding_setup_saved", resource_type="code_repository",
                    resource_id=repo.id, details={"workspace_id": workspace_id,
                                                  "fields": sorted(saved["coding_setup"])}))
    await db.commit()
    return await read_setup(db, repo, scope=await work_scope_project_ids(db, user))
