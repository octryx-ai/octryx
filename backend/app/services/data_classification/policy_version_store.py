"""Reads of classification policy versions and the small write helpers they share."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, ClassificationPolicyVersion
from ...models.runtime.governed_revision import (
    REVISION_STATE_DRAFT,
    REVISION_STATE_IN_REVIEW,
    REVISION_STATE_PUBLISHED,
)
from .policy_version_content import (
    APPROVAL_KIND,
    MAX_NOTE_CHARS,
    REFUSAL_NOT_FOUND,
    ClassificationVersionError,
    live_content,
)


async def list_versions(db: AsyncSession) -> list[ClassificationPolicyVersion]:
    stmt = select(ClassificationPolicyVersion).order_by(ClassificationPolicyVersion.version.desc())
    return list((await db.execute(stmt)).scalars())


async def get_version(db: AsyncSession, version: int) -> ClassificationPolicyVersion:
    stmt = select(ClassificationPolicyVersion).where(ClassificationPolicyVersion.version == int(version))
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise ClassificationVersionError(REFUSAL_NOT_FOUND, 404)
    return row


async def published_version(db: AsyncSession) -> ClassificationPolicyVersion | None:
    stmt = select(ClassificationPolicyVersion).where(ClassificationPolicyVersion.state == REVISION_STATE_PUBLISHED)
    return (await db.execute(stmt)).scalar_one_or_none()


async def open_draft(db: AsyncSession) -> ClassificationPolicyVersion | None:
    stmt = (select(ClassificationPolicyVersion)
            .where(ClassificationPolicyVersion.state.in_([REVISION_STATE_DRAFT, REVISION_STATE_IN_REVIEW]))
            .order_by(ClassificationPolicyVersion.version.desc()).limit(1))
    return (await db.execute(stmt)).scalar_one_or_none()


async def base_content(db: AsyncSession) -> dict[str, Any]:
    published = await published_version(db)
    return dict(published.content) if published is not None else await live_content(db)


# --- writes -------------------------------------------------------------------------------------------------------


def _audit(db: AsyncSession, actor_id: str, action: str, row: ClassificationPolicyVersion, **details: Any) -> None:
    db.add(AuditLog(user_id=actor_id, action=action, resource_type="classification_policy_version",
                    resource_id=row.id, details={"version": row.version, "digest": row.digest, **details}))


async def _next_version(db: AsyncSession) -> int:
    rows = await list_versions(db)
    return (rows[0].version + 1) if rows else 1


def _note(value: Any) -> str | None:
    return str(value or "").strip()[:MAX_NOTE_CHARS] or None



def approval_action(row: ClassificationPolicyVersion) -> str:
    return f"{APPROVAL_KIND}.publish:{row.id}:{row.digest}"
