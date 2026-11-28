"""Skill usage from octryx-claude and the usage read model of the catalog."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Skill, SkillUsageEvent, SkillVersion
from .delivery import PLUGIN_NAME
from .extension import SURFACE_OCTRYX_CLAUDE

SKILL_TOOL = "Skill"
INVOCATION_MODEL = "model"
INVOCATION_SLASH = "slash"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,99}$")


def skill_reference(tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("skill", "name", "command"):
        value = str(tool_input.get(key) or "").strip().lstrip("/").split(" ", 1)[0]
        if value:
            return value if _NAME.match(value) else ""
    return ""


async def record_claude_use(db: AsyncSession, *, reference: str, invocation: str, user_id: str | None,
                            project_id: str | None, session_id: str | None, decision: str = "allow",
                            source: str = "") -> SkillUsageEvent | None:
    if not reference:
        return None
    namespace, _, name = reference.partition(":") if ":" in reference else ("", "", reference)
    catalog = None
    version = None
    if namespace == PLUGIN_NAME:
        catalog = (await db.execute(select(Skill).where(Skill.name == name))).scalar_one_or_none()
        if catalog is not None and catalog.published_version_id:
            version = await db.get(SkillVersion, catalog.published_version_id)
    managed = catalog is not None and version is not None
    event = SkillUsageEvent(
        id=str(uuid.uuid4()), event_type="use" if decision == "allow" else "policy_denied",
        skill_id=catalog.id if managed else None, skill_name=(name if managed else reference)[:100],
        skill_version=version.version if managed else None, surface=SURFACE_OCTRYX_CLAUDE, invocation=invocation,
        bundle_digest=version.bundle_digest if managed else None,
        policy_status="success" if decision == "allow" else "denied", user_id=user_id, session_id=session_id,
        project_id=project_id, event_metadata={"unmanaged": not managed, "source": source[:40]},
    )
    db.add(event)
    await db.flush()
    return event


async def record_tool_check(db: AsyncSession, *, hook_input: dict[str, Any], answer: dict[str, Any],
                            user_id: str, project_id: str | None, session_id: str) -> None:
    if hook_input.get("tool_name") != SKILL_TOOL:
        return
    await record_claude_use(db, reference=skill_reference(hook_input.get("tool_input")),
                            invocation=INVOCATION_MODEL, user_id=user_id, project_id=project_id,
                            session_id=session_id, decision=str(answer.get("decision") or "deny"))


async def usage_summary(db: AsyncSession, *, since: datetime | None = None, skill_id: str | None = None
                        ) -> dict[str, Any]:
    filters = [SkillUsageEvent.event_type.in_(["get", "use", "policy_denied"])]
    if since is not None:
        filters.append(SkillUsageEvent.created_at >= since)
    if skill_id:
        filters.append(SkillUsageEvent.skill_id == skill_id)
    rows = (await db.execute(
        select(SkillUsageEvent.skill_id, SkillUsageEvent.skill_name, SkillUsageEvent.surface,
               SkillUsageEvent.invocation, SkillUsageEvent.event_type, func.count(SkillUsageEvent.id),
               func.max(SkillUsageEvent.created_at))
        .where(*filters)
        .group_by(SkillUsageEvent.skill_id, SkillUsageEvent.skill_name, SkillUsageEvent.surface,
                  SkillUsageEvent.invocation, SkillUsageEvent.event_type))).all()
    by_skill: dict[str, dict[str, Any]] = {}
    unmanaged: dict[str, int] = {}
    totals = {"uses": 0, "refusals": 0}
    for skill, name, surface, invocation, event_type, count, last in rows:
        key = "refusals" if event_type == "policy_denied" else "uses"
        totals[key] += int(count)
        if skill is None:
            if key == "uses" and name:
                unmanaged[str(name)] = unmanaged.get(str(name), 0) + int(count)
            continue
        entry = by_skill.setdefault(skill, {"skill_id": skill, "name": name, "uses": 0, "refusals": 0,
                                            "by_surface": {}, "last_used_at": None})
        entry[key] += int(count)
        if key == "uses":
            surface_key = f"{surface or 'platform_chat'}:{invocation or 'get'}"
            entry["by_surface"][surface_key] = entry["by_surface"].get(surface_key, 0) + int(count)
            stamp = last.isoformat() if last else None
            entry["last_used_at"] = max(filter(None, [entry["last_used_at"], stamp]), default=None)
    return {"skills": sorted(by_skill.values(), key=lambda item: (-item["uses"], item["name"] or "")),
            "unmanaged": [{"name": name, "uses": count} for name, count in sorted(unmanaged.items())],
            "totals": totals}


async def use_counts(db: AsyncSession) -> dict[str, int]:
    rows = (await db.execute(
        select(SkillUsageEvent.skill_id, func.count(SkillUsageEvent.id))
        .where(SkillUsageEvent.event_type.in_(["get", "use"]), SkillUsageEvent.skill_id.is_not(None))
        .group_by(SkillUsageEvent.skill_id))).all()
    return {str(skill): int(count) for skill, count in rows}


__all__ = ["INVOCATION_MODEL", "INVOCATION_SLASH", "SKILL_TOOL", "record_claude_use", "record_tool_check",
           "skill_reference", "use_counts", "usage_summary"]
