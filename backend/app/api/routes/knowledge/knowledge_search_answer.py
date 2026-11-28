"""The short cited answer on Knowledge Search."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import authorize_workspace
from ....services.knowledge.access.bindings import resolve_scope
from ....services.knowledge.answer.service import MAX_ANSWER_PASSAGES, answer_from_passages
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge", tags=["workspace-knowledge"])


class KnowledgeAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_text: str = Field(min_length=1, max_length=2000)
    evidence_keys: list[str] = Field(min_length=1, max_length=MAX_ANSWER_PASSAGES)


class KnowledgeAnswerSentence(BaseModel):
    text: str
    cites: list[str]


class KnowledgeAnswerResponse(BaseModel):
    state: Literal["ok", "no_answer", "needs_configuration", "denied", "unavailable"]
    sentences: list[KnowledgeAnswerSentence]
    cited_keys: list[str]


@router.post("/answer", response_model=KnowledgeAnswerResponse)
async def answer_knowledge_search(
    workspace_id: str,
    payload: KnowledgeAnswerRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        scope = await resolve_scope(db, authorized)
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return await answer_from_passages(
        db, scope=scope, query_text=payload.query_text, evidence_keys=payload.evidence_keys
    )
