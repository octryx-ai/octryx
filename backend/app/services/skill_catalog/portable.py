"""A catalog skill as a portable bundle (export packages and backups) and its governed import."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Skill, SkillCategory
from ...models.agent.skill_catalog import SKILL_KIND_SKILL
from .adoption import ensure_top_category
from .bundle import load_files
from .errors import SkillCatalogError
from .extension import normalize_extension
from .lifecycle import create_skill, published_version, save_draft, start_draft
from .spec import SKILL_FILE, SkillSpecError, parse_skill_md

PORTABLE_FORMAT = "skill_bundle"


async def portable_skill(db: AsyncSession, skill: Skill) -> dict[str, Any] | None:
    published = await published_version(db, skill)
    if published is None:
        return None
    category = await db.get(SkillCategory, published.category_id) if published.category_id else None
    texts = await load_files(db, published.files or [])
    return {
        "format": PORTABLE_FORMAT,
        "name": skill.name,
        "version": int(published.version),
        "category": category.label if category is not None else "Uncategorized",
        "licence_spdx": published.licence_spdx,
        "available_platform_chat": bool(published.available_platform_chat),
        "available_octryx_claude": bool(published.available_octryx_claude),
        "files": {path: texts[path] for path in sorted(texts)},
        "extension": normalize_extension(published.extension),
    }


def _bundle_files(entity: dict[str, Any]) -> dict[str, str]:
    if entity.get("format") != PORTABLE_FORMAT:
        raise SkillCatalogError("skill_package_format", 422,
                                message=f"A skill package carries the '{PORTABLE_FORMAT}' format.")
    files = entity.get("files")
    if not isinstance(files, dict) or not isinstance(files.get(SKILL_FILE), str):
        raise SkillCatalogError("skill_package_format", 422, message="A skill package carries its SKILL.md.")
    return {str(path): str(content) for path, content in files.items() if isinstance(content, str)}


async def import_portable_skill(
    db: AsyncSession, entity: dict[str, Any], *, name: str, overwrite_existing: bool, actor_id: str
) -> tuple[Skill, bool]:
    files = _bundle_files(entity)
    category = await ensure_top_category(db, str(entity.get("category") or "Uncategorized"))
    surfaces = {key: bool(entity.get(key, True)) for key in ("available_platform_chat", "available_octryx_claude")}
    extension = dict(entity.get("extension") or {})
    existing = (await db.execute(select(Skill).where(Skill.name == name))).scalar_one_or_none()
    if existing is not None:
        if not overwrite_existing:
            raise SkillCatalogError("skill_name_exists", 409, name=name)
        if existing.kind != SKILL_KIND_SKILL:
            raise SkillCatalogError("skill_kind_mismatch", 409, name=name, kind=existing.kind)
        row, _created = await start_draft(db, existing, actor_id=actor_id)
        current = {item["path"] for item in row.files or []}
        changes: dict[str, str | None] = {path: None for path in current if path not in files and path != SKILL_FILE}
        changes.update({path: content for path, content in files.items() if path != SKILL_FILE})
        await save_draft(db, existing, row, {
            "skill_md": files[SKILL_FILE], "files": changes, "extension": extension, "category_id": category.id,
            **surfaces}, if_match=row.digest, actor_id=actor_id)
        return existing, False
    try:
        parsed = parse_skill_md(files[SKILL_FILE])
    except SkillSpecError as error:
        issue = {"code": error.code, "message": error.message}
        raise SkillCatalogError("skill_spec_invalid", 422, issues=[issue]) from None
    skill, _row = await create_skill(db, {
        "name": name, "category_id": category.id, "frontmatter": parsed.frontmatter, "body": parsed.body,
        "files": {path: content for path, content in files.items() if path != SKILL_FILE},
        "extension": extension, "licence_spdx": entity.get("licence_spdx"), **surfaces}, actor_id=actor_id)
    return skill, True


__all__ = ["PORTABLE_FORMAT", "import_portable_skill", "portable_skill"]
