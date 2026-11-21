"""Skill sources (``skill_sources``): one row per Git repository + ref, plus one row for uploads.

A source carries what the update check needs (URL, ref, optional named connection for private repositories) and
what it last saw (commit, time, error). ``trust`` is the admin's label shown as *Official* / *Community* /
*Internal*; it never changes a decision. Credentials come only from a **global** named connection of a Git
connector (GitHub, GitLab, …): the first resolved ``*_token`` field.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection, Skill, SkillSource
from ...models.agent.skill_catalog import SOURCE_KIND_GIT, SOURCE_KIND_UPLOAD, SOURCE_TRUSTS
from ...models.runtime.named_connection import GLOBAL_SCOPE_KEY
from ...time_utils import utc_now
from ..named_connections.store import resolved_config, to_value
from .errors import SkillCatalogError

UPLOAD_LABEL = "Uploads"


def _trust(value: Any) -> str:
    trust = str(value or "community").strip().lower()
    if trust not in SOURCE_TRUSTS:
        raise SkillCatalogError("skill_source_trust_invalid", 422)
    return trust


def _label(url: str) -> str:
    parts = url.rstrip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else url


async def git_source(
    db: AsyncSession, *, url: str, ref: str, base_path: str, named_connection_id: str | None, trust: Any,
    label: Any, actor_id: str,
) -> SkillSource:
    existing = (await db.execute(select(SkillSource).where(
        SkillSource.kind == SOURCE_KIND_GIT, SkillSource.url == url, SkillSource.ref == ref))).scalar_one_or_none()
    now = utc_now()
    if existing is not None:
        existing.base_path = base_path
        existing.named_connection_id = named_connection_id or existing.named_connection_id
        if trust:
            existing.trust = _trust(trust)
        if label:
            existing.label = str(label).strip()[:200]
        existing.updated_at = now
        await db.flush()
        return existing
    source = SkillSource(kind=SOURCE_KIND_GIT, url=url, ref=ref, base_path=base_path,
                         named_connection_id=named_connection_id, trust=_trust(trust),
                         label=str(label or "").strip()[:200] or _label(url), created_by=actor_id, created_at=now,
                         updated_at=now)
    db.add(source)
    await db.flush()
    return source


async def upload_source(db: AsyncSession, *, actor_id: str) -> SkillSource:
    existing = (await db.execute(select(SkillSource).where(SkillSource.kind == SOURCE_KIND_UPLOAD))).scalars().first()
    if existing is not None:
        return existing
    now = utc_now()
    source = SkillSource(kind=SOURCE_KIND_UPLOAD, label=UPLOAD_LABEL, trust="internal", base_path="",
                         created_by=actor_id, created_at=now, updated_at=now)
    db.add(source)
    await db.flush()
    return source


async def source_token(db: AsyncSession, named_connection_id: str | None) -> str | None:
    if not named_connection_id:
        return None
    row = await db.get(ConnectorNamedConnection, str(named_connection_id))
    if row is None or row.scope_key != GLOBAL_SCOPE_KEY:
        raise SkillCatalogError("skill_source_connection_not_found", 422,
                                message="Use a global named connection of a Git connector.")
    config = await resolved_config(db, to_value(row))
    token = next((str(value) for key, value in sorted(config.items()) if key.endswith("_token") and value), None)
    if token is None:
        raise SkillCatalogError("skill_source_connection_without_token", 422)
    return token


async def get_source(db: AsyncSession, source_id: str) -> SkillSource:
    source = await db.get(SkillSource, source_id)
    if source is None:
        raise SkillCatalogError("skill_source_not_found", 404)
    return source


async def list_sources(db: AsyncSession) -> list[dict[str, Any]]:
    counts = dict((await db.execute(select(Skill.source_id, func.count(Skill.id)).group_by(Skill.source_id))).all())
    rows = (await db.execute(select(SkillSource).order_by(SkillSource.kind, SkillSource.label))).scalars()
    return [serialize_source(row, int(counts.get(row.id, 0))) for row in rows]


async def update_source(db: AsyncSession, source: SkillSource, payload: dict[str, Any]) -> SkillSource:
    if "trust" in payload:
        source.trust = _trust(payload["trust"])
    if "label" in payload:
        source.label = str(payload.get("label") or "").strip()[:200] or source.label
    if "named_connection_id" in payload:
        source.named_connection_id = str(payload.get("named_connection_id") or "") or None
    source.updated_at = utc_now()
    await db.flush()
    return source


def serialize_source(source: SkillSource, skills: int = 0) -> dict[str, Any]:
    return {
        "id": source.id,
        "kind": source.kind,
        "label": source.label,
        "trust": source.trust,
        "url": source.url,
        "ref": source.ref,
        "base_path": source.base_path or "",
        "named_connection_id": source.named_connection_id,
        "licence_detected": source.licence_detected,
        "last_checked_at": source.last_checked_at.isoformat() if source.last_checked_at else None,
        "last_seen_commit": source.last_seen_commit,
        "last_error": source.last_error,
        "skills": skills,
    }


__all__ = [
    "get_source",
    "git_source",
    "list_sources",
    "serialize_source",
    "source_token",
    "update_source",
    "upload_source",
]
