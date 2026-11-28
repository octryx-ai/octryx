"""Agent catalog classification: categories, priority scores and the chat agent option payload. It reads configured
agent text, never a user prompt, and never selects the agent a turn runs with."""

from typing import Any

from ..models import AgentDefinition
from .agent_mode import DEFAULT_AGENT_MODE_KEY

__all__ = [
    "AGENT_CATALOG_CATEGORY_DEFINITIONS",
    "agent_catalog_group_payload",
    "classify_agent_catalog_entry",
    "agent_catalog_priority_score",
    "serialize_chat_agent_option",
]


AGENT_CATALOG_CATEGORY_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("delivery-pm", "Delivery & PM"),
    ("engineering", "Engineering"),
    ("operations", "Operations"),
    ("documentation-knowledge", "Documentation & Knowledge"),
    ("security-review", "Security & Review"),
    ("reporting", "Reporting"),
    ("specialized", "Specialized"),
)


def agent_catalog_group_payload(category_id: str, category_name: str, *, agent_count: int) -> dict[str, Any]:
    return {
        "id": category_id,
        "name": category_name,
        "slug": category_id,
        "description": f"{category_name} agent catalog",
        "category": "catalog",
        "projectId": None,
        "position": 0,
        "isActive": True,
        "agentCount": agent_count,
    }


def classify_agent_catalog_entry(*, agent: AgentDefinition) -> tuple[str, str, bool]:
    haystack = " ".join(
        part
        for part in (
            agent.name,
            agent.description,
            agent.goal,
            agent.agent_type,
        )
        if str(part or "").strip()
    ).lower()
    if any(token in haystack for token in ("analytics", "report", "cost anomaly", "presentation", "powerpoint")):
        return "reporting", "Reporting", True
    if any(token in haystack for token in ("security", "review", "compliance", "vulnerability")):
        return "security-review", "Security & Review", True
    if any(
        token in haystack for token in ("backend engineer", "frontend engineer", "coding", "implementation", "refactor")
    ):
        return "engineering", "Engineering", True
    if any(
        token in haystack
        for token in ("jira", "sprint", "release", "project manager", "delivery", "roadmap", "handover")
    ):
        return "delivery-pm", "Delivery & PM", True
    if any(token in haystack for token in ("incident", "sre", "deployment validation", "k8s", "on-call", "operations")):
        return "operations", "Operations", True
    if any(token in haystack for token in ("knowledge", "document", "confluence", "readme", "trace sync")):
        return "documentation-knowledge", "Documentation & Knowledge", True
    if any(token in haystack for token in ("stable jira worker",)):
        return "delivery-pm", "Delivery & PM", True
    return "specialized", "Specialized", False


def agent_catalog_priority_score(*, agent: AgentDefinition, category_id: str) -> int:
    normalized_name = str(agent.name or "").strip().lower()
    score = len(list(getattr(agent, "steps", []) or []))
    if category_id == "delivery-pm":
        if "jira sprint planner" in normalized_name or "jira release coordinator" in normalized_name:
            score += 40
        if "project manager" in normalized_name:
            score += 30
        if "stable jira worker" in normalized_name:
            score -= 10
    elif category_id == "engineering":
        if "backend engineer" in normalized_name:
            score += 20
        if "frontend engineer" in normalized_name:
            score += 18
    elif category_id == "operations":
        if "incident triage" in normalized_name:
            score += 20
        if "sre investigator" in normalized_name:
            score += 18
    elif category_id == "documentation-knowledge":
        if "knowledge builder" in normalized_name:
            score += 24
        if "document updater" in normalized_name:
            score += 10
    elif category_id == "security-review":
        if "security reviewer" in normalized_name:
            score += 20
    elif category_id == "reporting":
        if "analytics reporter" in normalized_name:
            score += 20
        if "presentation designer" in normalized_name:
            score -= 6
    return int(score)


def serialize_chat_agent_option(
    *,
    agent: AgentDefinition,
    category_id: str,
    category_name: str,
    is_core: bool,
    is_primary: bool,
) -> dict[str, Any]:
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description or "",
        "agentType": agent.agent_type or DEFAULT_AGENT_MODE_KEY,
        "groupId": category_id,
        "groupName": category_name,
        "category": category_name,
        "isCore": is_core,
        "isPrimary": is_primary,
    }
