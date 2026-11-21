"""The trusted-source registry and search settings of a Workspace (search control plane).

Thin: authenticate, authorize the Workspace, delegate to ``services/web_search``. Reading needs
Workspace access; changing a Workspace entry, the Workspace's search mode or running the canary
needs the Workspace's admin or owner role; changing a platform entry needs a platform admin.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ...db import get_db
from ...models import Project, User
from ...models.project.web_trusted_sources import SCOPE_PLATFORM, WebTrustedSource
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.auth import get_current_user
from ...services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.web_search.blocklist import platform_blocklist
from ...services.web_search.health import canary, quarantine_reason
from ...services.web_search.patterns import InvalidSourcePatternError
from ...services.web_search.providers import provider_config
from ...services.web_search.registry import decide_source, list_sources, put_source, source_in_scope
from ...services.web_search.service import (
    MODE_OPEN,
    MODE_TRUSTED_ONLY,
    WEB_SEARCH_POLICY_KEY,
    search_mode_of,
    stored_project_config,
)
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/web-search", tags=["web-search"])


class SourceRequest(BaseModel):
    pattern: str = Field(min_length=4, max_length=300)
    state: Literal["trusted", "blocked"]
    scope: Literal["workspace", "platform"] = "workspace"
    products: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(default="", max_length=500)


class DecisionRequest(BaseModel):
    state: Literal["trusted", "blocked"]


class ModeRequest(BaseModel):
    mode: Literal["open", "trusted_only"]


async def _authorized(db, user, workspace_id: str, *, author: bool) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=author)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


async def _require_platform_admin(db, user: User) -> None:
    if not await is_global_admin(db, user.id):
        raise HTTPException(status_code=403, detail="Platform admin role required for platform-wide sources.")


def _entry(row: WebTrustedSource) -> dict:
    return {
        "id": row.id,
        "scope": "platform" if row.scope_key == SCOPE_PLATFORM else "workspace",
        "pattern": row.pattern,
        "products": list(row.products or []),
        "state": row.state,
        "origin": row.origin,
        "reason": row.reason,
        "evidence_url": row.evidence_url,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _overview(db, authorized: AuthorizedWorkspace, user: User) -> dict:
    config = await stored_project_config(db, authorized.project_id)
    provider = provider_config(config)
    held = quarantine_reason(provider.name) if provider else None
    return {
        "mode": search_mode_of(config),
        "provider": {
            "name": provider.name if provider else None,
            "state": "needs_configuration" if provider is None else ("unavailable" if held else "ok"),
            "quarantine_reason": held,
            "data_policy_class": provider.data_policy_class if provider else None,
        },
        "blocklist_version": platform_blocklist().version,
        "may_edit_platform": await is_global_admin(db, user.id),
        "sources": [_entry(row) for row in await list_sources(db, project_id=authorized.project_id)],
    }


@router.get("/sources")
async def get_sources(
    workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=False)
    return await _overview(db, authorized, current_user)


@router.post("/sources")
async def add_source(
    workspace_id: str,
    body: SourceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    if body.scope == "platform":
        await _require_platform_admin(db, current_user)
    try:
        await put_source(
            db,
            project_id=None if body.scope == "platform" else authorized.project_id,
            pattern=body.pattern,
            state=body.state,
            products=body.products,
            reason=body.reason,
            user_id=current_user.id,
        )
    except InvalidSourcePatternError as error:
        raise HTTPException(status_code=422, detail=f"Source pattern refused ({error.reason}).") from None
    await db.commit()
    return await _overview(db, authorized, current_user)


async def _source(db, authorized: AuthorizedWorkspace, user: User, source_id: str) -> WebTrustedSource:
    row = await source_in_scope(db, source_id=source_id, project_id=authorized.project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    if row.scope_key == SCOPE_PLATFORM:
        await _require_platform_admin(db, user)
    return row


@router.patch("/sources/{source_id}")
async def decide(
    workspace_id: str,
    source_id: str,
    body: DecisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trust or block an entry, including an agent's proposal."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    row = await _source(db, authorized, current_user, source_id)
    await decide_source(db, row, state=body.state, user_id=current_user.id)
    await db.commit()
    return await _overview(db, authorized, current_user)


@router.delete("/sources/{source_id}")
async def remove(
    workspace_id: str,
    source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    await db.delete(await _source(db, authorized, current_user, source_id))
    await db.commit()
    return await _overview(db, authorized, current_user)


@router.put("/mode")
async def set_mode(
    workspace_id: str,
    body: ModeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """``trusted_only`` restricts the chat's web search to trusted sources; ``open`` applies the blocklists."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    project = await db.get(Project, authorized.project_id)
    config = dict(project.config or {})
    config[WEB_SEARCH_POLICY_KEY] = {"mode": MODE_TRUSTED_ONLY if body.mode == MODE_TRUSTED_ONLY else MODE_OPEN}
    project.config = config
    flag_modified(project, "config")
    await db.commit()
    return await _overview(db, authorized, current_user)


@router.post("/canary")
async def run_canary(
    workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Probe the provider with the fixed canary query; a failing probe quarantines it."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    provider = provider_config(await stored_project_config(db, authorized.project_id))
    if provider is None:
        return {"provider": None, "healthy": False, "reason": "provider_not_configured"}
    return await canary(provider)
