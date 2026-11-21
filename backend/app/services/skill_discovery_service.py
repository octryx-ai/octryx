"""Platform chat delivery of catalog skills: ``skill_search`` and ``skill_get``.

Both read **published versions** through the one effective-set function (``skill_catalog.effective``) for the
surface ``platform_chat``: availability, the Workspace surface switch, the assignment mode with selected skills
and categories, blocked skills, the agent's blocked skills and the user's roles. On top of that the chat keeps its
two runtime checks: the agent's allowed-skill list and the required tools of the turn.

``skill_search`` returns metadata only; ``skill_get`` returns one content level (summary = description, card =
description + section outline or the version's card override, full = the SKILL.md body) or one reference file
(``resource="references/…"``). Scripts never reach chat. ``diagnostics`` (admin/operator only) loads the latest
version of a skill that is not delivered, for troubleshooting; it is recorded as such.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Skill, SkillVersion
from .skill_catalog.bundle import KIND_SCRIPT, bundle_files
from .skill_catalog.effective import Candidate, candidates
from .skill_catalog.extension import SURFACE_PLATFORM_CHAT, card_text, normalize_extension, token_cost
from .skill_usage_trace_service import record_skill_get_usage, record_skill_search_usage

DEFAULT_SKILL_SEARCH_LIMIT = 8
MAX_SKILL_SEARCH_LIMIT = 20
MAX_SUMMARY_CHARS = 800
MAX_CARD_CHARS = 1600
MAX_FULL_CHARS = 6000
CONTENT_LEVELS = ("summary", "card", "full")

#: The fixed message per effective-set reason (shown to the agent and stored on the usage trace).
DENIALS = {
    "not_available_on_surface": "Skill is not available in platform chat",
    "surface_off_for_workspace": "Skills are turned off for platform chat in the current project",
    "skills_off_for_workspace": "Skills are disabled for the current project",
    "not_assigned": "Skill is not assigned to the current project",
    "blocked_by_workspace": "Skill is blocked by the current project",
    "blocked_by_agent": "Skill is blocked by the current agent",
    "role_not_allowed": "Skill is not allowed for the current user roles",
}
NOT_PUBLISHED = "Skill is not published"


@dataclass(slots=True)
class SkillAccessContext:
    user_roles: list[str]
    user_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    agent_definition: dict[str, Any] | None = None
    request_id: str | None = None
    available_tool_names: set[str] | None = None
    diagnostics: bool = False


def _keys(skill: Skill) -> set[str]:
    return {skill.id, skill.name, f"skill:{skill.id}"}


def _preferences(agent_definition: dict[str, Any] | None) -> dict[str, set[str]]:
    raw = (agent_definition or {}).get("skillPreferences") or (agent_definition or {}).get("skill_preferences")
    raw = raw if isinstance(raw, dict) else {}
    # An agent only narrows; its preferred skills rank first.
    preferred = {str(item) for item in raw.get("preferred_skill_ids") or []}
    return {"preferred_skill_ids": preferred}


def _denial(candidate: Candidate, context: SkillAccessContext) -> str:
    if candidate.reason:
        return DENIALS.get(candidate.reason, candidate.reason)
    required = set(normalize_extension(candidate.version.extension)["tools"][SURFACE_PLATFORM_CHAT]["required"])
    available = context.available_tool_names
    if available is not None and required and not required <= available:
        return f"Skill requires unavailable tools: {', '.join(sorted(required - available))}"
    return ""


async def _chat_candidates(db: AsyncSession, context: SkillAccessContext) -> list[Candidate]:
    return await candidates(db, project_id=context.project_id, surface=SURFACE_PLATFORM_CHAT,
                            user_roles=list(context.user_roles), agent_definition=context.agent_definition)


def _category_matches(candidate: Candidate, category: str | None) -> bool:
    if not category:
        return True
    keys = {candidate.category.key if candidate.category else "", candidate.parent.key if candidate.parent else ""}
    return category in keys


def _texts(candidate: Candidate) -> dict[str, str]:
    frontmatter = candidate.version.frontmatter or {}
    extension = normalize_extension(candidate.version.extension)
    return {
        "name": candidate.skill.name.lower(),
        "summary": str(frontmatter.get("description") or "").lower(),
        "trigger": str(frontmatter.get("when_to_use") or "").lower(),
        "category": " ".join(filter(None, [candidate.category.key if candidate.category else "",
                                           candidate.category.label if candidate.category else ""])).lower(),
        "tool": " ".join(extension["tools"][SURFACE_PLATFORM_CHAT]["required"]).lower(),
    }


_WEIGHTS = {"name": 4.0, "trigger": 3.0, "summary": 2.0, "category": 1.0, "tool": 1.0}


def _score(candidate: Candidate, terms: list[str], preferences: dict[str, set[str]]) -> tuple[float, list[str]]:
    score, reasons = (0.1, ["catalog"]) if not terms else (0.0, [])
    for field, haystack in _texts(candidate).items() if terms else ():
        matches = [term for term in terms if term in haystack]
        if matches:
            score += _WEIGHTS[field] * len(matches)
            reasons.append(field)
    keys = _keys(candidate.skill)
    if preferences["preferred_skill_ids"] & keys:
        score, reasons = score + 2.0, [*reasons, "agent_preferred"]
    return score, reasons


def _result(candidate: Candidate, *, score: float, reasons: list[str]) -> dict[str, Any]:
    version = candidate.version
    extension = normalize_extension(version.extension)
    resources = [entry["path"] for entry in version.files or [] if entry["path"] != "SKILL.md"
                 and entry.get("kind") not in {KIND_SCRIPT, "manifest"}]
    return {
        "id": candidate.skill.id,
        "name": candidate.skill.name,
        "summary": str((version.frontmatter or {}).get("description") or ""),
        "category": candidate.category.key if candidate.category else candidate.skill.category,
        "version": version.version,
        "status": "active",
        "source": candidate.skill.source,
        "score": round(score, 3),
        "match_reason": ", ".join(reasons[:4]),
        "required_tools": extension["tools"][SURFACE_PLATFORM_CHAT]["required"],
        "available_content_levels": list(CONTENT_LEVELS),
        "resources": resources,
    }


async def search_skills(db: AsyncSession, *, query: str, category: str | None, source: str | None, limit: int,
                        access_context: SkillAccessContext) -> dict[str, Any]:
    effective_limit = _bounded_limit(limit)
    terms = [term for term in re.findall(r"[a-z0-9_\-]{2,}", str(query or "").lower()) if term]
    preferences = _preferences(access_context.agent_definition)
    scored: list[dict[str, Any]] = []
    rejected: list[str] = []
    for candidate in await _chat_candidates(db, access_context):
        if not _category_matches(candidate, category) or (source and candidate.skill.source != source):
            continue
        denial = _denial(candidate, access_context)
        if denial:
            if candidate.reason not in {"not_available_on_surface", "not_assigned"}:
                rejected.append(denial)
            continue
        score, reasons = _score(candidate, terms, preferences)
        if terms and score <= 0:
            continue
        scored.append(_result(candidate, score=score, reasons=reasons or ["catalog"]))
    scored.sort(key=lambda item: (-float(item["score"]), item["category"], item["name"]))
    results = scored[:effective_limit]
    await record_skill_search_usage(db, query=query, results=results, rejected_reasons=rejected,
                                    context=access_context)
    return {"query": query, "count": len(results), "total_matches": len(scored), "results": results,
            "policy": {"statuses": ["published"], "content": "metadata_only", "requires_skill_get": True}}


async def _load(db: AsyncSession, skill_id: str | None, name: str | None) -> Skill | None:
    if str(skill_id or "").strip():
        return await db.get(Skill, str(skill_id).strip())
    if str(name or "").strip():
        return (await db.execute(select(Skill).where(Skill.name == str(name).strip()))).scalar_one_or_none()
    return None


async def _diagnostic_version(db: AsyncSession, skill: Skill) -> SkillVersion | None:
    stmt = select(SkillVersion).where(SkillVersion.skill_id == skill.id).order_by(SkillVersion.version.desc())
    return (await db.execute(stmt.limit(1))).scalar_one_or_none()


def _has_diagnostic_role(roles: list[str]) -> bool:
    return bool({"admin", "operator"} & {str(role or "").strip().lower() for role in roles})


async def get_skill_content(db: AsyncSession, *, skill_id: str | None, name: str | None, content_level: str,
                            access_context: SkillAccessContext, resource: str | None = None) -> dict[str, Any]:
    level = str(content_level or "summary").strip().lower()
    skill = await _load(db, skill_id, name)
    if skill is None:
        await record_skill_get_usage(db, skill=None, content_level=level, policy_status="not_found",
                                     policy_reason="Skill not found", context=access_context)
        return {"error": "Skill not found"}
    found = next((item for item in await _chat_candidates(db, access_context) if item.skill.id == skill.id), None)
    denial = _denial(found, access_context) if found is not None else NOT_PUBLISHED
    version = found.version if found is not None else None
    status = "success"
    if denial:
        if not (access_context.diagnostics and _has_diagnostic_role(access_context.user_roles)):
            await record_skill_get_usage(db, skill=skill, content_level=level, policy_status="denied",
                                         policy_reason=denial, context=access_context)
            return {"error": denial}
        version = version or await _diagnostic_version(db, skill)
        status = "diagnostics"
        if version is None:
            return {"error": NOT_PUBLISHED}
    if resource is None and level not in CONTENT_LEVELS:
        await record_skill_get_usage(db, skill=skill, content_level=level, policy_status="invalid_request",
                                     policy_reason="Invalid content level", context=access_context)
        return {"error": "content_level must be one of: summary, card, full"}
    content, max_chars, level = await _content(db, version, level, resource)
    if content is None:
        return {"error": f"Resource not found: {resource}"}
    truncated = len(content) > max_chars
    await record_skill_get_usage(db, skill=skill, content_level=level, policy_status=status,
                                 policy_reason=denial if status == "diagnostics" else "", context=access_context,
                                 version=version)
    extension = normalize_extension(version.extension)
    return {
        "id": skill.id, "name": skill.name,
        "category": found.category.key if found is not None and found.category else skill.category,
        "version": version.version, "status": "active" if status == "success" else version.state,
        "source": skill.source, "content_level": level, "content": content[:max_chars].rstrip(),
        "truncated": truncated,
        "required_tools": extension["tools"][SURFACE_PLATFORM_CHAT]["required"],
        "optional_tools": extension["tools"][SURFACE_PLATFORM_CHAT]["optional"],
        "output_contract": extension["output_contract"], "safety_rules": extension["safety_rules"],
        "approval_rules": extension["approval_rules"], "token_cost_estimate": token_cost(version.body or ""),
        "diagnostics": status == "diagnostics",
    }


async def _content(db: AsyncSession, version: SkillVersion, level: str, resource: str | None
                   ) -> tuple[str | None, int, str]:
    if resource is not None:
        entry = next((item for item in version.files or [] if item["path"] == resource
                      and item["path"] != "SKILL.md" and item.get("kind") not in {KIND_SCRIPT, "manifest"}), None)
        if entry is None:
            return None, 0, "resource"
        return (await bundle_files(db, [entry]))[0].content, MAX_FULL_CHARS, "resource"
    description = str((version.frontmatter or {}).get("description") or "")
    body = str(version.body or "").strip("\n")
    if level == "summary":
        return description, MAX_SUMMARY_CHARS, level
    if level == "card":
        return card_text(description, body, normalize_extension(version.extension)), MAX_CARD_CHARS, level
    return body, MAX_FULL_CHARS, level


def _bounded_limit(value: Any) -> int:
    try:
        parsed = int(value or DEFAULT_SKILL_SEARCH_LIMIT)
    except (TypeError, ValueError):
        parsed = DEFAULT_SKILL_SEARCH_LIMIT
    return max(1, min(parsed, MAX_SKILL_SEARCH_LIMIT))
