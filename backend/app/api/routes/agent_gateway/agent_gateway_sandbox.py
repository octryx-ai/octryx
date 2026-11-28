"""Workspace sandbox network for governed Claude Code sessions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.agent_gateway.sandbox_policy import (
    MAX_DOMAINS,
    set_workspace_sandbox_domains,
    workspace_sandbox_domains,
)
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    authorize_workspace,
)
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ..knowledge._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/agent-gateway", tags=["agent-gateway"])


class SandboxDomainsRequest(BaseModel):
    allowed_domains: list[str] = Field(default_factory=list, max_length=MAX_DOMAINS)


async def _authorized(db: AsyncSession, user: User, workspace_id: str) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id)
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


async def _view(db: AsyncSession, authorized: AuthorizedWorkspace) -> dict:
    domains = await workspace_sandbox_domains(db, authorized.project_id)
    if domains is None:
        raise HTTPException(status_code=409, detail="policy_invalid")
    return {"workspace_id": authorized.project_id, "may_author": authorized.may_author,
            "allowed_domains": list(domains)}


@router.get("/sandbox")
async def get_sandbox(
    workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return await _view(db, await _authorized(db, current_user, workspace_id))


@router.put("/sandbox")
async def set_sandbox(
    workspace_id: str,
    body: SandboxDomainsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id)
    if not authorized.may_author:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL)
    await set_workspace_sandbox_domains(
        db, project_id=authorized.project_id, domains=body.allowed_domains, actor_user_id=str(current_user.id)
    )
    return await _view(db, authorized)
