"""Ticket keys in free text, by explicit patterns only."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_source_sync import KnowledgeSourceConnector
from .profile_types import StructuredProfile

NODE_JIRA = "JiraIssue"
_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,30}$")


def ticket_key(node_type: str, number: str) -> str:
    return f"jira:{number}" if node_type == NODE_JIRA else f"servicenow:{number}"


def jira_pattern(project_keys: tuple[str, ...]) -> re.Pattern[str] | None:
    keys = sorted({key for key in project_keys if _PROJECT_KEY.fullmatch(key)}, key=lambda key: (-len(key), key))
    if not keys:
        return None
    return re.compile(r"\b(?:" + "|".join(map(re.escape, keys)) + r")-[1-9][0-9]{0,6}\b")


def ticket_mentions(text: str, profile: StructuredProfile, jira: re.Pattern[str] | None) -> list[tuple[str, str, int]]:
    found: dict[tuple[str, str], int] = {}
    for node_type, pattern in profile.ticket_patterns:
        for match in pattern.finditer(text):
            found.setdefault((node_type, match.group(0)), match.start())
    if jira is not None:
        for match in jira.finditer(text):
            found.setdefault((NODE_JIRA, match.group(0)), match.start())
    items = [(kind, number, offset) for (kind, number), offset in found.items()]
    return sorted(items, key=lambda item: (item[2], item[1]))


def find_tickets(text: str, profile: StructuredProfile, jira: re.Pattern[str] | None) -> list[tuple[str, str]]:
    return [(kind, number) for kind, number, _ in ticket_mentions(text, profile, jira)]


async def jira_project_keys(db: AsyncSession, project_id: str) -> tuple[str, ...]:
    rows = await db.execute(
        select(KnowledgeSourceConnector.scope).where(
            KnowledgeSourceConnector.project_id == project_id, KnowledgeSourceConnector.kind == "jira"
        )
    )
    keys: set[str] = set()
    for (scope,) in rows.all():
        for key in (scope or {}).get("project_keys") or ():
            if isinstance(key, str) and _PROJECT_KEY.fullmatch(key):
                keys.add(key)
    return tuple(sorted(keys))


__all__ = ["NODE_JIRA", "find_tickets", "jira_pattern", "jira_project_keys", "ticket_key", "ticket_mentions"]
