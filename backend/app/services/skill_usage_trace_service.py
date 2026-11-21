from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Skill, SkillUsageEvent, SkillVersion
from .skill_catalog.extension import SURFACE_PLATFORM_CHAT, token_cost

MAX_QUERY_EXCERPT_CHARS = 500
MAX_REASON_CHARS = 300


async def record_skill_search_usage(
    db: AsyncSession,
    *,
    query: str,
    results: list[dict[str, Any]],
    rejected_reasons: list[str],
    context: Any,
) -> None:
    db.add(
        SkillUsageEvent(
            id=str(uuid.uuid4()),
            event_type="search",
            query_excerpt=_bounded_text(query, MAX_QUERY_EXCERPT_CHARS),
            returned_skill_ids=[str(item.get("id")) for item in results if item.get("id")],
            surface=SURFACE_PLATFORM_CHAT,
            invocation="search",
            policy_status="success",
            policy_reason=_reason_summary(rejected_reasons),
            user_id=getattr(context, "user_id", None),
            session_id=getattr(context, "session_id", None),
            project_id=getattr(context, "project_id", None),
            agent_id=_agent_id(context),
            request_id=getattr(context, "request_id", None),
            event_metadata={
                "result_count": len(results),
                "rejected_reason_counts": dict(Counter(rejected_reasons)),
            },
        )
    )


async def record_skill_get_usage(
    db: AsyncSession,
    *,
    skill: Skill | None,
    content_level: str,
    policy_status: str,
    policy_reason: str = "",
    context: Any,
    version: SkillVersion | None = None,
) -> None:
    """One ``get`` event; a refused request is ``policy_denied`` and names no skill (no metadata leak).

    ``diagnostics`` (an admin/operator loading a skill that is not delivered) is recorded as a get with that status.
    """
    successful = skill is not None and version is not None and policy_status in {"success", "diagnostics"}
    db.add(
        SkillUsageEvent(
            id=str(uuid.uuid4()),
            event_type="get" if successful else "policy_denied",
            skill_id=skill.id if successful else None,
            skill_name=skill.name if successful else None,
            skill_version=int(version.version) if successful else None,
            surface=SURFACE_PLATFORM_CHAT,
            invocation="get",
            bundle_digest=version.bundle_digest if successful else None,
            content_level=content_level,
            policy_status=policy_status,
            policy_reason=_bounded_text(policy_reason, MAX_REASON_CHARS),
            token_cost_estimate=token_cost(version.body or "") if successful else 0,
            user_id=getattr(context, "user_id", None),
            session_id=getattr(context, "session_id", None),
            project_id=getattr(context, "project_id", None),
            agent_id=_agent_id(context),
            request_id=getattr(context, "request_id", None),
        )
    )


async def summarize_skill_usage(db: AsyncSession) -> dict[str, dict[str, Any]]:
    count_rows = await db.execute(
        select(
            SkillUsageEvent.skill_id,
            func.count(SkillUsageEvent.id),
            func.max(SkillUsageEvent.created_at),
        )
        .where(
            SkillUsageEvent.event_type == "get",
            SkillUsageEvent.policy_status == "success",
            SkillUsageEvent.skill_id.is_not(None),
        )
        .group_by(SkillUsageEvent.skill_id)
    )
    summary = {
        str(skill_id): {
            "load_count": int(count or 0),
            "last_used_at": last_used.isoformat() if last_used else None,
            "common_queries": [],
        }
        for skill_id, count, last_used in count_rows.all()
        if skill_id
    }

    query_rows = await db.execute(
        select(SkillUsageEvent.returned_skill_ids, SkillUsageEvent.query_excerpt)
        .where(
            SkillUsageEvent.event_type == "search",
            SkillUsageEvent.query_excerpt != "",
        )
        .order_by(desc(SkillUsageEvent.created_at))
        .limit(200)
    )
    query_counts: dict[str, Counter[str]] = {}
    for returned_skill_ids, query_excerpt in query_rows.all():
        if not isinstance(returned_skill_ids, list) or not query_excerpt:
            continue
        for skill_id in returned_skill_ids:
            key = str(skill_id or "").strip()
            if not key:
                continue
            query_counts.setdefault(key, Counter())[str(query_excerpt)] += 1
    for skill_id, counter in query_counts.items():
        summary.setdefault(skill_id, {"load_count": 0, "last_used_at": None, "common_queries": []})
        summary[skill_id]["common_queries"] = [query for query, _ in counter.most_common(3)]
    return summary


def _agent_id(context: Any) -> str | None:
    agent_definition = getattr(context, "agent_definition", None)
    if not isinstance(agent_definition, dict):
        return None
    return str(agent_definition.get("id") or "").strip() or None


def _reason_summary(reasons: list[str]) -> str:
    if not reasons:
        return ""
    counts = Counter(reason for reason in reasons if reason)
    return _bounded_text("; ".join(f"{reason}: {count}" for reason, count in counts.most_common(5)), MAX_REASON_CHARS)


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()
