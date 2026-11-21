"""The catalog read model: list rows with filters and header counts, the detail of one skill, versions.

List filters are explicit fields, never a guess: ``q`` (substring of name, description or tag), ``category_id``
(the category and its children), ``tag``, ``state`` (``published`` | ``draft`` | ``in_review`` | ``update`` |
``retired``), ``surface`` (``platform_chat`` | ``octryx_claude``), ``source_id``, ``kind``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Skill, SkillCategory, SkillSource, SkillVersion
from ...models.runtime.governed_revision import REVISION_STATE_IN_REVIEW, REVISION_STATE_PUBLISHED
from ..policy_engine.review import history_rows, review_view
from .categories import subtree_ids
from .extension import SURFACE_OCTRYX_CLAUDE, SURFACE_PLATFORM_CHAT
from .lifecycle import OPEN_STATES
from .reach import delivered_count, skill_reach
from .scanner import new_findings
from .usage import use_counts

STATES = ("published", "draft", "in_review", "update", "retired")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def version_summary(row: SkillVersion | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"version": row.version, "state": row.state, "digest": row.digest, "updated_at": _iso(row.updated_at)}


def serialize_version(row: SkillVersion, *, content: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id, "version": row.version, "state": row.state, "digest": row.digest,
        "bundle_digest": row.bundle_digest, "category_id": row.category_id,
        "available_platform_chat": bool(row.available_platform_chat),
        "available_octryx_claude": bool(row.available_octryx_claude), "licence_spdx": row.licence_spdx,
        "scripts_allowed": bool(row.scripts_allowed), "scripts_reason": row.scripts_reason,
        "scripts_allowed_by": row.scripts_allowed_by, "acknowledged_findings": list(row.acknowledged_findings or []),
        "upstream": {"source_id": row.upstream_source_id, "path": row.upstream_path, "commit": row.upstream_commit,
                     "bundle_digest": row.upstream_bundle_digest} if row.upstream_source_id else None,
        "base_version": row.base_version, "note": row.note, "created_by": row.created_by,
        "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at), "submitted_by": row.submitted_by,
        "submitted_at": _iso(row.submitted_at), "approval_id": row.approval_id, "published_by": row.published_by,
        "published_at": _iso(row.published_at), "retired_at": _iso(row.retired_at),
        "files": list(row.files or []), "security_report": row.security_report or {},
        "merge_report": row.merge_report, "launch_spec": row.launch_spec,
    }
    if content:
        payload.update(frontmatter=dict(row.frontmatter or {}), body=row.body or "",
                       extension=dict(row.extension or {}))
    return payload


async def _versions_by_skill(db: AsyncSession, skill_ids: list[str]) -> dict[str, dict[str, SkillVersion]]:
    if not skill_ids:
        return {}
    rows = (await db.execute(select(SkillVersion).where(
        SkillVersion.skill_id.in_(skill_ids),
        SkillVersion.state.in_([*OPEN_STATES, REVISION_STATE_PUBLISHED])))).scalars()
    found: dict[str, dict[str, SkillVersion]] = {}
    for row in rows:
        found.setdefault(row.skill_id, {})["published" if row.state == REVISION_STATE_PUBLISHED else "open"] = row
    return found


def _category_path(category: SkillCategory | None, categories: dict[str, SkillCategory]) -> dict[str, Any] | None:
    if category is None:
        return None
    parent = categories.get(category.parent_id) if category.parent_id else None
    return {"id": category.id, "key": category.key, "label": category.label,
            "path": [parent.label, category.label] if parent else [category.label]}


def _update_available(skill: Skill) -> bool:
    status = skill.upstream_status if isinstance(skill.upstream_status, dict) else {}
    return bool(status.get("update_available"))


async def list_rows(db: AsyncSession, filters: dict[str, Any]) -> dict[str, Any]:
    skills = list((await db.execute(select(Skill).order_by(Skill.name))).scalars())
    categories = {row.id: row for row in (await db.execute(select(SkillCategory))).scalars()}
    sources = {row.id: row for row in (await db.execute(select(SkillSource))).scalars()}
    versions = await _versions_by_skill(db, [skill.id for skill in skills])
    uses = await use_counts(db)
    reach = await skill_reach(db)
    rows = []
    for skill in skills:
        found = versions.get(skill.id, {})
        published, opened = found.get("published"), found.get("open")
        working = opened or published
        category = categories.get(working.category_id) if working else categories.get(skill.category_id or "")
        source = sources.get(skill.source_id or "")
        rows.append({
            "id": skill.id, "name": skill.name, "kind": skill.kind, "tags": list(skill.tags or []),
            "description": str(((working.frontmatter if working else {}) or {}).get("description") or ""),
            "category": _category_path(category, categories),
            "published": version_summary(published), "open": version_summary(opened),
            "available": {SURFACE_PLATFORM_CHAT: bool(published and published.available_platform_chat),
                          SURFACE_OCTRYX_CLAUDE: bool(published and published.available_octryx_claude)},
            "source": {"id": source.id, "label": source.label, "trust": source.trust, "kind": source.kind}
            if source else None,
            "tracking_mode": skill.tracking_mode, "update_available": _update_available(skill),
            "upstream_status": skill.upstream_status, "uses": uses.get(skill.id, 0),
            "workspaces": delivered_count(reach.get(skill.id, [])),
        })
    counts = {
        "published": sum(1 for row in rows if row["published"]),
        "drafts": sum(1 for row in rows if row["open"] and row["open"]["state"] == "draft"),
        "in_review": sum(1 for row in rows if row["open"] and row["open"]["state"] == REVISION_STATE_IN_REVIEW),
        "updates": sum(1 for row in rows if row["update_available"]),
        "total": len(rows),
    }
    filtered = [row for row in rows if await _matches(db, row, filters)]
    return {"items": filtered, "counts": counts}


async def _matches(db: AsyncSession, row: dict[str, Any], filters: dict[str, Any]) -> bool:
    needle = str(filters.get("q") or "").strip().lower()
    if needle and not any(needle in text.lower() for text in [row["name"], row["description"], *row["tags"]]):
        return False
    if filters.get("category_id"):
        wanted = await subtree_ids(db, str(filters["category_id"]))
        if not row["category"] or row["category"]["id"] not in wanted:
            return False
    if filters.get("tag") and str(filters["tag"]).lower() not in row["tags"]:
        return False
    if filters.get("kind") and row["kind"] != filters["kind"]:
        return False
    if filters.get("source_id") and (row["source"] or {}).get("id") != filters["source_id"]:
        return False
    if filters.get("surface") and not row["available"].get(str(filters["surface"])):
        return False
    state = filters.get("state")
    return not state or {
        "published": bool(row["published"]),
        "draft": bool(row["open"] and row["open"]["state"] == "draft"),
        "in_review": bool(row["open"] and row["open"]["state"] == REVISION_STATE_IN_REVIEW),
        "update": row["update_available"],
        "retired": not row["published"] and not row["open"],
    }.get(str(state), False)


def _findings(row: SkillVersion | None) -> list[dict[str, Any]]:
    report = row.security_report if row is not None and isinstance(row.security_report, dict) else {}
    return [item for item in report.get("findings") or [] if isinstance(item, dict)]


async def detail(db: AsyncSession, skill: Skill, *, viewer_id: str) -> dict[str, Any]:
    rows = list((await db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill.id)
                                  .order_by(SkillVersion.version.desc()))).scalars())
    published = next((row for row in rows if row.state == REVISION_STATE_PUBLISHED), None)
    opened = next((row for row in rows if row.state in OPEN_STATES), None)
    categories = {row.id: row for row in (await db.execute(select(SkillCategory))).scalars()}
    source = await db.get(SkillSource, skill.source_id) if skill.source_id else None
    history = await history_rows(db, rows, [serialize_version(row, content=False) for row in rows])
    working = opened or published
    return {
        "id": skill.id, "name": skill.name, "kind": skill.kind, "tags": list(skill.tags or []),
        "owner_id": skill.owner_id, "tracking_mode": skill.tracking_mode, "pinned_commit": skill.pinned_commit,
        "upstream_path": skill.upstream_path, "upstream_status": skill.upstream_status,
        "source": {"id": source.id, "label": source.label, "trust": source.trust, "kind": source.kind,
                   "url": source.url, "ref": source.ref} if source else None,
        "category": _category_path(categories.get(working.category_id) if working else None, categories),
        "published": serialize_version(published) if published else None,
        "open": serialize_version(opened) if opened else None,
        "review": await review_view(db, opened, viewer_id=viewer_id) if opened and opened.approval_id else None,
        "new_findings": new_findings(_findings(opened), _findings(published)) if opened else [],
        "versions": history,
    }


__all__ = ["STATES", "detail", "list_rows", "serialize_version", "version_summary"]
