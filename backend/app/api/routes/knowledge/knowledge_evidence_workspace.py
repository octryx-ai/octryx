"""Workspace Knowledge enablement and the read model of its settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ....services.knowledge.ledger.errors import EvidenceLedgerError, EvidenceStoreNotConfiguredError
from ....services.knowledge.ledger.lifecycle import backfill_embeddings
from ....services.knowledge.projection.workspace_classification_default import workspace_classification_view
from ....services.knowledge.projection.workspace_provisioning import (
    STATE_NEEDS_CONFIGURATION,
    STATE_READY,
    enable_workspace_knowledge,
)
from ....services.knowledge.rerank.admission_state import reranker_admission
from ....services.knowledge.runtime import get_evidence_runtime
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge", tags=["workspace-knowledge"])

_STATUS_BY_STATE = {STATE_READY: 200, STATE_NEEDS_CONFIGURATION: 503}


@router.post("/enable")
async def enable_knowledge(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Enable Knowledge for the Workspace (confirm its Evidence index); safe to repeat."""
    try:
        authorized = await authorize_workspace(
            db, current_user=current_user, workspace_id=workspace_id, require_author=True
        )
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    result = await enable_workspace_knowledge(db, authorized=authorized, actor_id=current_user.id)
    return JSONResponse(
        status_code=_STATUS_BY_STATE.get(result.state, 503), content=result.as_dict(authorized.project_id)
    )


@router.get("/settings")
async def knowledge_settings(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The Workspace's data classification (effective, source, Instance default) and reranker admission."""
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return {
        "workspace_id": authorized.project_id,
        "data_classification": await workspace_classification_view(db, authorized.project_id),
        "reranker": await reranker_admission(db, project_id=authorized.project_id),
    }


@router.post("/embedding/backfill")
async def backfill_knowledge_embeddings(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Owe vectors in the Instance's embedding space for every current revision; safe to repeat."""
    try:
        authorized = await authorize_workspace(
            db, current_user=current_user, workspace_id=workspace_id, require_author=True
        )
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    try:
        runtime = get_evidence_runtime()
        if runtime.embedding is None:
            raise EvidenceStoreNotConfiguredError()
        owed = await backfill_embeddings(
            db, authorized=authorized, actor_id=current_user.id, space_key=runtime.embedding.space.key
        )
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return {
        "workspace_id": authorized.project_id,
        "embedding_space": runtime.embedding.space.key,
        "revisions_owed": owed,
        "projection": "embedding",
    }
