"""Validation verdicts and publication of Agent Definition revisions. Both change revision rows only, never the live
aggregate."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentDefinitionRevision
from ..models.agent.agent_definition_revision import (
    REVISION_STATUS_DRAFT,
    REVISION_STATUS_INVALID,
    REVISION_STATUS_PUBLISHED,
)
from ..time_utils import utc_now
from .agent_definition_revision_store import ALREADY_PUBLISHED_DETAIL
from .agent_definition_validation import validate_definition_snapshot
from .agent_definition_validation_issues import ValidationResult


async def validate_revision(
    db: AsyncSession, *, revision: AgentDefinitionRevision
) -> ValidationResult:
    # A published revision is immutable: its stored verdict is never overwritten.
    result = await validate_definition_snapshot(db, revision.snapshot)
    if revision.status != REVISION_STATUS_PUBLISHED:
        revision.validation = result.as_dict()
        revision.status = REVISION_STATUS_DRAFT if result.ok else REVISION_STATUS_INVALID
        await db.flush()
    return result


async def publish_revision(
    db: AsyncSession, *, revision: AgentDefinitionRevision, published_by: str
) -> AgentDefinitionRevision:
    if revision.status == REVISION_STATUS_PUBLISHED:
        raise HTTPException(status_code=409, detail=ALREADY_PUBLISHED_DETAIL)
    result = await validate_definition_snapshot(db, revision.snapshot)
    if not result.ok:
        raise HTTPException(
            status_code=422,
            detail={"message": "Revision is not valid", **result.as_dict()},
        )
    from .platform_agents.publish_governance import check_platform_agent_publish

    await check_platform_agent_publish(db, revision=revision, publisher_id=published_by)
    revision.validation = result.as_dict()
    revision.status = REVISION_STATUS_PUBLISHED
    revision.published_by = published_by
    revision.published_at = utc_now()
    await db.flush()
    return revision
