"""Row-level writes of the prompt catalog, shared by the seed step and the admin service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import AuditLog
from ...models.runtime.governed_revision import (
    REVISION_STATE_PUBLISHED,
    REVISION_STATE_RETIRED,
)
from ...models.runtime.prompt_template import PROMPT_SCOPE_WORKSPACE, PromptTemplate, PromptTemplateVersion, uuid_pk
from ...time_utils import utc_now
from .contract import prompt_digest
from .scopes import normalized_scope, scope_key

CHANGE_NOTE_MAX = 500


async def find_template(db: AsyncSession, *, key: str, scope_type: str, scope_id: str | None) -> PromptTemplate | None:
    return (
        await db.execute(
            select(PromptTemplate)
            .options(selectinload(PromptTemplate.versions))
            .where(PromptTemplate.key == key, PromptTemplate.scope_key == scope_key(scope_type, scope_id))
        )
    ).scalar_one_or_none()


async def create_template(
    db: AsyncSession, *, key: str, scope_type: str, scope_id: str | None, created_by: str
) -> PromptTemplate:
    kind, ident = normalized_scope(scope_type, scope_id)
    now = utc_now()
    template = PromptTemplate(
        key=key,
        scope_type=kind,
        scope_id=ident,
        scope_key=scope_key(kind, ident),
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template, attribute_names=["versions"])
    return template


async def templates_in_scope(db: AsyncSession, *, scope_type: str, scope_id: str | None) -> dict[str, PromptTemplate]:
    rows = (
        await db.execute(
            select(PromptTemplate)
            .options(selectinload(PromptTemplate.versions))
            .where(PromptTemplate.scope_key == scope_key(scope_type, scope_id))
        )
    ).scalars()
    return {template.key: template for template in rows}


def stage_template_with_published_version(
    db: AsyncSession,
    *,
    key: str,
    scope_type: str,
    scope_id: str | None,
    body: str,
    source: str,
    created_by: str,
    change_note: str,
) -> tuple[PromptTemplate, PromptTemplateVersion]:
    kind, ident = normalized_scope(scope_type, scope_id)
    now = utc_now()
    template = PromptTemplate(
        id=uuid_pk(),
        key=key,
        scope_type=kind,
        scope_id=ident,
        scope_key=scope_key(kind, ident),
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    version = PromptTemplateVersion(
        id=uuid_pk(),
        template=template,
        version=1,
        state=REVISION_STATE_PUBLISHED,
        source=source,
        body=body,
        digest=prompt_digest(body),
        change_note=str(change_note or "")[:CHANGE_NOTE_MAX],
        created_by=created_by,
        created_at=now,
        updated_at=now,
        published_by=created_by,
        published_at=now,
    )
    db.add(template)
    db.add(version)
    return template, version


async def _next_version_number(db: AsyncSession, template: PromptTemplate) -> int:
    current = (
        await db.execute(
            select(func.max(PromptTemplateVersion.version)).where(PromptTemplateVersion.template_id == template.id)
        )
    ).scalar_one()
    return int(current or 0) + 1


async def add_version(
    db: AsyncSession,
    *,
    template: PromptTemplate,
    body: str,
    source: str,
    state: str,
    created_by: str,
    change_note: str,
) -> PromptTemplateVersion:
    now = utc_now()
    version = PromptTemplateVersion(
        template_id=template.id,
        version=await _next_version_number(db, template),
        state=state,
        source=source,
        body=body,
        digest=prompt_digest(body),
        change_note=str(change_note or "")[:CHANGE_NOTE_MAX],
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    if state == REVISION_STATE_PUBLISHED:
        await retire_published(db, template=template, retired_by=created_by)
        version.published_by = created_by
        version.published_at = now
    db.add(version)
    template.updated_at = now
    await db.flush()
    return version


async def published_version(db: AsyncSession, template: PromptTemplate) -> PromptTemplateVersion | None:
    return (
        await db.execute(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.template_id == template.id,
                PromptTemplateVersion.state == REVISION_STATE_PUBLISHED,
            )
        )
    ).scalar_one_or_none()


async def retire_published(
    db: AsyncSession, *, template: PromptTemplate, retired_by: str
) -> PromptTemplateVersion | None:
    current = await published_version(db, template)
    if current is None:
        return None
    retire_version(current, retired_by=retired_by)
    await db.flush()
    return current


def retire_version(version: PromptTemplateVersion, *, retired_by: str) -> None:
    now = utc_now()
    version.state = REVISION_STATE_RETIRED
    version.retired_by = retired_by
    version.retired_at = now
    version.updated_at = now


async def publish_existing(
    db: AsyncSession,
    *,
    template: PromptTemplate,
    version: PromptTemplateVersion,
    published_by: str,
    approval_id: str | None,
) -> PromptTemplateVersion:
    await retire_published(db, template=template, retired_by=published_by)
    now = utc_now()
    version.state = REVISION_STATE_PUBLISHED
    version.published_by = published_by
    version.published_at = now
    version.approval_id = approval_id
    version.updated_at = now
    template.updated_at = now
    await db.flush()
    return version


def add_audit(
    db: AsyncSession, *, user_id: str, action: str, template: PromptTemplate, details: dict[str, object]
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type="prompt_template",
            resource_id=template.id,
            project_id=template.scope_id if template.scope_type == PROMPT_SCOPE_WORKSPACE else None,
            details={"key": template.key, "scope": template.scope_key, **details},
        )
    )


__all__ = [
    "add_audit",
    "add_version",
    "create_template",
    "find_template",
    "publish_existing",
    "published_version",
    "retire_published",
    "retire_version",
    "stage_template_with_published_version",
    "templates_in_scope",
]
