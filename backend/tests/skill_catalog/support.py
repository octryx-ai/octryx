"""Shared helpers for the skill catalog tests."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Approval, Skill, SkillCategory, SkillVersion
from app.services.skill_catalog.adoption import approval_action, ensure_top_category
from app.services.skill_catalog.bundle import BundleFile
from app.services.skill_catalog.extension import SURFACE_PLATFORM_CHAT, normalize_extension
from app.services.skill_catalog.settings import LICENCE_INTERNAL
from app.services.skill_catalog.spec import render_skill_md
from app.services.skill_catalog.versions import VersionContent, new_draft_row, sync_identity, write_content
from app.time_utils import utc_now

BASE = "/api/v1/admin/skill-catalog"


def skill_md(name: str, description: str = "Check things.", body: str = "\n# Checks\n\nRun the checks.\n",
             extra: str = "") -> str:
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\n{body}"


async def category(db, key: str) -> SkillCategory:
    return (await db.execute(select(SkillCategory).where(SkillCategory.key == key))).scalar_one()


async def draft_skill(db, category_id: str, name: str | None = None, *, files: list[BundleFile] | None = None,
                      actor_id: str | None = None, **content) -> tuple[Skill, SkillVersion]:
    skill = Skill(id=str(uuid.uuid4()), name=name or f"skill-{uuid.uuid4().hex[:8]}", category="x")
    db.add(skill)
    await db.flush()
    row = await new_draft_row(db, skill, actor_id=actor_id, note=None, base_version=None)
    db.add(row)
    await write_content(db, skill, row, VersionContent(
        files=files or [BundleFile("SKILL.md", skill_md(skill.name))], extension=content.pop("extension", {}),
        category_id=category_id, **content))
    return skill, row


async def published_skill(db, category_id: str, name: str | None = None, *, approver_id: str,
                          files: list[BundleFile] | None = None, **content) -> tuple[Skill, SkillVersion]:
    skill, row = await draft_skill(db, category_id, name, files=files, actor_id=approver_id, **content)
    approval = Approval(requested_by=approver_id, approved_by=approver_id, status="approved",
                        action=approval_action(row), reason="test")
    db.add(approval)
    await db.flush()
    now = utc_now()
    row.state, row.approval_id, row.published_by, row.published_at = "published", approval.id, approver_id, now
    await db.flush()
    await sync_identity(db, skill, row)
    await db.flush()
    return skill, row


async def force_publish(db, skill_id: str, *, approver_id: str) -> SkillVersion:
    row = (await db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill_id,
                                                       SkillVersion.state.in_(["draft", "in_review"])))).scalar_one()
    approval = Approval(requested_by=approver_id, approved_by=approver_id, status="approved",
                        action=approval_action(row), reason="test")
    db.add(approval)
    previous = (await db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill_id,
                                                            SkillVersion.state == "published"))).scalar_one_or_none()
    if previous is not None:
        previous.state, previous.retired_at = "retired", utc_now()
    await db.flush()
    row.state, row.approval_id, row.published_by, row.published_at = "published", approval.id, approver_id, utc_now()
    await db.flush()
    await sync_identity(db, await db.get(Skill, skill_id), row)
    await db.commit()
    return row


async def publish_chat_skill(db, name: str, *, approver_id: str, description: str, category: str = "utility",
                             body: str = "", when_to_use: str | None = None, required_tools: tuple[str, ...] = (),
                             allowed_roles: tuple[str, ...] = (), card_content: str = "", executor_type: str | None = None,
                             in_chat: bool = True) -> tuple[Skill, SkillVersion]:
    top = await ensure_top_category(db, category)
    frontmatter = {"name": name, "description": description}
    if when_to_use:
        frontmatter["when_to_use"] = when_to_use
    extension = normalize_extension({
        "tools": {SURFACE_PLATFORM_CHAT: {"required": list(required_tools), "optional": []}},
        "allowed_roles": list(allowed_roles), "card_content": card_content, "executor_type": executor_type,
    })
    files = [BundleFile("SKILL.md", render_skill_md(frontmatter, f"\n{body or f'# {name}'}\n"))]
    return await published_skill(db, top.id, name, approver_id=approver_id, files=files, extension=extension,
                                 available_platform_chat=in_chat, available_octryx_claude=False,
                                 licence_spdx=LICENCE_INTERNAL)
