"""Agent catalog helpers of the chat UI and the project preference lookups they share."""

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    AgentDefinition,
    Project,
    User,
)
from ...services.agent_catalog_policy import (
    AGENT_CATALOG_CATEGORY_DEFINITIONS,
    agent_catalog_group_payload,
    agent_catalog_priority_score,
    classify_agent_catalog_entry,
    serialize_chat_agent_option,
)
from ...services.agent_visibility import visible_agent_clause

__all__ = [
    "_list_chat_agent_catalog",
]

# One categorized catalog entry: agent, category id, category name, is core, priority score.
_CatalogEntry = tuple[AgentDefinition, str, str, bool, int]


async def _load_project_config(db: AsyncSession, project_id: str | None) -> dict[str, Any]:
    project = (
        (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none() if project_id else None
    )
    return dict(project.config or {}) if project and isinstance(project.config, dict) else {}


def _preference_map(project_config: dict[str, Any], key: str) -> dict:
    return project_config.get(key) if isinstance(project_config.get(key), dict) else {}


def _preference_status(preferences: dict, key: str) -> str:
    return str(((preferences.get(key) or {}).get("status")) or "").strip().lower()


def _agent_rank(agent: AgentDefinition) -> tuple[int, float]:
    created_at = getattr(agent, "created_at", None)
    timestamp = created_at.timestamp() if created_at is not None else 0.0
    return (len(list(getattr(agent, "steps", []) or [])), timestamp)


async def _load_deduped_chat_agents(
    db: AsyncSession, *, user: User, project_id: str | None
) -> list[AgentDefinition]:
    agent_query = (
        select(AgentDefinition)
        .options(selectinload(AgentDefinition.steps), selectinload(AgentDefinition.group))
        .where(
            await visible_agent_clause(db, user.id),
            AgentDefinition.is_active.is_(True),
            # The composer offers exactly the chat-selectable agents (Assistant, Engineer).
            AgentDefinition.chat_selectable.is_(True),
        )
    )
    if project_id:
        agent_query = agent_query.where(
            or_(AgentDefinition.project_id == project_id, AgentDefinition.project_id.is_(None))
        )
    rows = (await db.execute(agent_query)).scalars().all()

    deduped: dict[tuple[str, str, str | None], AgentDefinition] = {}
    for agent in rows:
        key = (
            str(agent.name or "").strip().lower(),
            str(agent.agent_type or "").strip().lower(),
            str(agent.project_id or "").strip() or None,
        )
        current = deduped.get(key)
        if current is None or _agent_rank(agent) > _agent_rank(current):
            deduped[key] = agent
    return sorted(deduped.values(), key=lambda item: (str(item.project_id or ""), item.name.lower()))


def _categorize_agents(
    agents: list[AgentDefinition],
    *,
    agent_preferences: dict,
) -> tuple[dict[str, list[_CatalogEntry]], dict[str, int]]:
    categorized_agents: dict[str, list[_CatalogEntry]] = {}
    category_counts: dict[str, int] = {}
    for agent in agents:
        category_id, category_name, is_core = classify_agent_catalog_entry(agent=agent)
        priority_score = agent_catalog_priority_score(agent=agent, category_id=category_id)
        pref_status = _preference_status(agent_preferences, agent.id)
        if pref_status == "hidden":
            continue
        if pref_status == "primary":
            priority_score += 100
        category_counts[category_id] = category_counts.get(category_id, 0) + 1
        categorized_agents.setdefault(category_id, []).append(
            (agent, category_id, category_name, is_core, priority_score)
        )
    return categorized_agents, category_counts


def _serialize_agent_options(categorized_agents: dict[str, list[_CatalogEntry]]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for category_id, items in categorized_agents.items():
        ranked = sorted(items, key=lambda item: (-item[4], str(item[0].name or "").lower()))
        primary_agent_id = ranked[0][0].id if ranked and category_id != "specialized" else ""
        for agent, _, category_name, is_core, _priority_score in ranked:
            is_primary = bool(primary_agent_id and agent.id == primary_agent_id)
            options.append(
                serialize_chat_agent_option(
                    agent=agent,
                    category_id=category_id,
                    category_name=category_name,
                    is_core=is_core,
                    is_primary=is_primary,
                )
            )
    options.sort(
        key=lambda item: (
            str(item.get("groupName") or ""),
            0 if item.get("isPrimary") else 1,
            str(item.get("name") or "").lower(),
        )
    )
    return options


async def _list_chat_agent_catalog(
    db: AsyncSession,
    *,
    user: User,
    project_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    project_config = await _load_project_config(db, project_id)
    agent_preferences = _preference_map(project_config, "project_agent_preferences")
    agents = await _load_deduped_chat_agents(db, user=user, project_id=project_id)
    categorized_agents, category_counts = _categorize_agents(
        agents,
        agent_preferences=agent_preferences,
    )
    options = _serialize_agent_options(categorized_agents)
    groups = [
        agent_catalog_group_payload(category_id, category_name, agent_count=category_counts.get(category_id, 0))
        for category_id, category_name in AGENT_CATALOG_CATEGORY_DEFINITIONS
        if category_counts.get(category_id, 0) > 0
    ]
    return options, groups
