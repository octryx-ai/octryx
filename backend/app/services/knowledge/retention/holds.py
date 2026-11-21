"""The durable claim one retention pass has on one object, and the ingestion's fast refusal.

The ingestion boundary writes the immutable object *before* it commits the revision, so
"this object has no governed reference" is only ever true at the moment it is measured. What
serializes an operator pass and an ingestion of the same object is **not** this row — it is
the transaction-scoped publication boundary both sides hold
(``services/knowledge/object_publication_lock.py``), because only the database can serialize
two transactions in two processes. This row does two things the lock cannot:

- **One pass per object.** A pass **commits** a hold on ``(project_id, object_key)``, and the
  unique constraint means a second pass simply loses and skips the key. A lock that is
  released at commit cannot carry that across transactions.
- **A fast refusal instead of a wait.** The ingestion path consults the hold before it
  writes, and answers its retryable ``unavailable`` state while one is live, so a request
  does not sit inside a database transaction waiting for an operator pass to finish. The
  next attempt writes the same content address and succeeds once the hold is gone.

An ingestion that read the hold table before the hold was committed is not protected by this
row at all — it is protected by the publication boundary, which it holds from before its
write until its commit, so a pass cannot run in the middle of it.

``expires_at`` bounds a hold whose operator process died: an expired hold blocks nothing and
is taken over by the next pass, so a crash cannot park a Workspace's object forever. The
expiry is deliberately far shorter than the policy's minimum object age, so an expired hold
can never be the reason an in-flight ingestion is unprotected.

This module holds no policy and no S3 access: it is pure PostgreSQL state, which is why the
ingestion path may import it without reaching the operator-owned capability.
"""

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
    """One committed hold: the pass owns this key until it releases or the hold expires."""

    hold_id: str
    project_id: str
    object_key: str
    expires_at: datetime


async def object_key_is_held(
    db: AsyncSession, *, project_id: str, object_key: str, now: datetime | None = None
) -> bool:
    """True while a live retention hold exists for this exact object of this Workspace.

    Called by the ingestion path (``services/knowledge_evidence/ingestion.py``) under the
    publication boundary, before the object is written. An expired row is not a hold.
    """
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


async def acquire_hold(
    db: AsyncSession,
    *,
    project_id: str,
    object_key: str,
    finding_id: str,
    acquired_by: str,
    hold_seconds: int = DEFAULT_HOLD_SECONDS,
) -> AcquiredHold | None:
    """Commit a hold on one object, or return ``None`` when another pass holds it.

    Committed on purpose: an uncommitted hold is invisible to the ingestion session, and
    invisible is the same as absent. A live hold of another pass is a skip, never a
    takeover; an expired one is taken over, which is what makes a crashed pass recoverable.
    """
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
    """Drop one own hold. Uncommitted: the caller commits it with the finding's outcome."""
    if type(hold) is not AcquiredHold:
        raise InvalidRetentionRequestError()
    await db.execute(
        delete(KnowledgeObjectRetentionHold).where(KnowledgeObjectRetentionHold.id == hold.hold_id)
    )
