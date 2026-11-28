"""The durable claim one retention pass has on one object, and the ingestion's fast refusal. Pure PostgreSQL state, so
ingestion may import it."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_object_retention import KnowledgeObjectRetentionHold
from ....time_utils import utc_now
from .errors import InvalidRetentionRequestError

logger = logging.getLogger(__name__)

DEFAULT_HOLD_SECONDS = 900
MIN_HOLD_SECONDS = 30
MAX_HOLD_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class AcquiredHold:
    hold_id: str
    project_id: str
    object_key: str
    expires_at: datetime


async def object_key_is_held(
    db: AsyncSession, *, project_id: str, object_key: str, now: datetime | None = None
) -> bool:
    # Called under the publication boundary, before the object is written; an expired row is not a hold.
    if type(project_id) is not str or type(object_key) is not str or not project_id or not object_key:
        raise InvalidRetentionRequestError()
    moment = now if now is not None else utc_now()
    if type(moment) is not datetime:
        raise InvalidRetentionRequestError()
    statement = select(KnowledgeObjectRetentionHold.id).where(
        KnowledgeObjectRetentionHold.project_id == project_id,
        KnowledgeObjectRetentionHold.object_key == object_key,
        KnowledgeObjectRetentionHold.expires_at > moment,
    )
    return (await db.execute(statement)).first() is not None


async def held_object_keys(db: AsyncSession, *, project_id: str, now: datetime) -> set[str]:
    rows = await db.execute(
        select(KnowledgeObjectRetentionHold.object_key).where(
            KnowledgeObjectRetentionHold.project_id == project_id,
            KnowledgeObjectRetentionHold.expires_at > now,
        )
    )
    return {row[0] for row in rows.all()}


async def acquire_hold(
    db: AsyncSession,
    *,
    project_id: str,
    object_key: str,
    finding_id: str,
    acquired_by: str,
    hold_seconds: int = DEFAULT_HOLD_SECONDS,
) -> AcquiredHold | None:
    # Committed on purpose: an uncommitted hold is invisible to ingestion. A live hold is skipped, an expired one taken
    # over.
    if type(hold_seconds) is not int or not MIN_HOLD_SECONDS <= hold_seconds <= MAX_HOLD_SECONDS:
        raise InvalidRetentionRequestError()
    if type(finding_id) is not str or type(acquired_by) is not str or not finding_id or not acquired_by:
        raise InvalidRetentionRequestError()
    now = utc_now()
    existing = (
        await db.execute(
            select(KnowledgeObjectRetentionHold).where(
                KnowledgeObjectRetentionHold.project_id == project_id,
                KnowledgeObjectRetentionHold.object_key == object_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.expires_at > now:
            return None
        logger.info("Knowledge object retention hold expired and is reused: workspace=%s", project_id)
        await db.delete(existing)
        await db.flush()
    # Identity and expiry are decided here, not read back after the commit, so no attribute
    # of a committed row has to be refreshed to answer what this pass now owns.
    hold_id = str(uuid.uuid4())
    expires_at = now + timedelta(seconds=hold_seconds)
    db.add(
        KnowledgeObjectRetentionHold(
            id=hold_id,
            project_id=project_id,
            object_key=object_key,
            finding_id=finding_id,
            acquired_by=acquired_by,
            acquired_at=now,
            expires_at=expires_at,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        # The unique constraint is the arbiter: a concurrent pass committed first. The
        # database error itself is dropped, it carries constraint and statement text.
        await db.rollback()
        logger.info("Knowledge object retention hold lost to a concurrent pass: workspace=%s", project_id)
        return None
    return AcquiredHold(
        hold_id=hold_id, project_id=project_id, object_key=object_key, expires_at=expires_at
    )


async def release_hold(db: AsyncSession, hold: AcquiredHold) -> None:
    if type(hold) is not AcquiredHold:
        raise InvalidRetentionRequestError()
    await db.execute(
        delete(KnowledgeObjectRetentionHold).where(KnowledgeObjectRetentionHold.id == hold.hold_id)
    )
