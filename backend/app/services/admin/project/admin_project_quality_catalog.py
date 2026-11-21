"""Catalog and serialization helpers for admin project quality views."""

from __future__ import annotations

from typing import Any

from ....models import AgentDefinition

PROJECT_AGENT_CATEGORY_DEFINITIONS: list[tuple[str, str, tuple[str, ...]]] = [
    ("delivery-pm", "Delivery & PM", ("jira", "release", "sprint", "project manager", "delivery", "pm")),
    ("engineering", "Engineering", ("backend", "frontend", "engineer", "coding", "repo", "repository")),
    ("operations", "Operations", ("incident", "sre", "ops", "investigator", "deployment", "k8s", "on-call")),
    ("documentation-knowledge", "Documentation & Knowledge", ("document", "knowledge", "confluence", "readme")),
    ("security-review", "Security & Review", ("security", "review", "compliance")),
    ("reporting", "Reporting", ("analytics", "report", "reporting", "cost", "presentation")),
]


def normalize_project_agent_preferences(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = config.get("project_agent_preferences")
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for agent_id, payload in raw.items():
        if not str(agent_id or "").strip() or not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "").strip().lower()
        if status in {"primary", "hidden"}:
            normalized[str(agent_id)] = {"status": status}
    return normalized


def classify_project_agent_category(
    *,
    agent_name: str,
    agent_description: str,
    agent_type: str,
) -> tuple[str, str, bool]:
    normalized_name = agent_name.strip().lower()
    haystack = " ".join(
        [
            normalized_name,
            agent_description.strip().lower(),
            agent_type.strip().lower(),
        ]
    )
    if "project manager" in normalized_name:
        return "delivery-pm", "Delivery & PM", True
    if "readme knowledge builder" in normalized_name or "knowledge builder" in normalized_name:
        return "documentation-knowledge", "Documentation & Knowledge", True
    if any(marker in haystack for marker in ("analytics", "report", "reporting", "cost", "presentation", "powerpoint")):
        return "reporting", "Reporting", True
    if any(marker in haystack for marker in ("document", "knowledge", "confluence", "readme")):
        return "documentation-knowledge", "Documentation & Knowledge", True
    if any(marker in haystack for marker in ("incident", "sre", "investigator", "ops", "deployment", "k8s", "on-call")):
        return "operations", "Operations", True
    if any(marker in haystack for marker in ("security", "review", "compliance")):
        return "security-review", "Security & Review", True
    if any(marker in haystack for marker in ("backend", "frontend", "engineer", "coding")):
        return "engineering", "Engineering", True
    if any(marker in haystack for marker in ("jira", "release", "sprint", "project manager", "delivery", "pm")):
        return "delivery-pm", "Delivery & PM", True
    for key, label, markers in PROJECT_AGENT_CATEGORY_DEFINITIONS:
        if any(marker in haystack for marker in markers):
            return key, label, key != "specialized"
    agent_type_normalized = agent_type.strip().lower()
    if agent_type_normalized == "self_review":
        return "security-review", "Security & Review", True
    if agent_type_normalized in {"documentation", "knowledge"}:
        return "documentation-knowledge", "Documentation & Knowledge", True
    if agent_type_normalized == "diagnosis":
        return "operations", "Operations", True
    return "specialized", "Specialized", False


def serialize_project_agent_catalog(
    agent: AgentDefinition,
    *,
    preference_status: str = "",
) -> dict[str, Any]:
    category_key, category_label, is_core = classify_project_agent_category(
        agent_name=agent.name or "",
        agent_description=agent.description or "",
        agent_type=agent.agent_type or "",
    )
    normalized_name = str(agent.name or "").strip().lower()
    primary_score = 0
    for marker, score in (
        ("project manager", 35),
        ("jira sprint planner", 40),
        ("jira release coordinator", 40),
        ("security reviewer", 35),
        ("incident triage", 30),
        ("sre investigator", 28),
        ("backend engineer", 26),
        ("frontend engineer", 24),
        ("knowledge builder", 25),
        ("analytics reporter", 28),
    ):
        if marker in normalized_name:
            primary_score += score
    if "presentation designer" in normalized_name:
        primary_score -= 10
    if "stable jira worker" in normalized_name:
        primary_score -= 8
    if agent.group_id:
        primary_score += 5
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description or "",
        "goal": agent.goal or "",
        "agent_type": agent.agent_type,
        "category_key": category_key,
        "category_label": category_label,
        "is_core": bool(is_core),
        "group_id": agent.group_id or "",
        "group_name": agent.group.name if getattr(agent, "group", None) else "",
        "runtime_target_id": agent.runtime_target_id or "",
        "step_count": len(getattr(agent, "steps", []) or []),
        "primary_score": int(primary_score),
        "preference_status": preference_status or "",
        "created_at": agent.created_at.isoformat() if getattr(agent, "created_at", None) else None,
        "updated_at": agent.updated_at.isoformat() if getattr(agent, "updated_at", None) else None,
    }


def build_project_agent_role_summary(agent_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    seen_categories: set[str] = set()
    categories = PROJECT_AGENT_CATEGORY_DEFINITIONS + [("specialized", "Specialized", tuple())]
    for category_key, category_label, _ in categories:
        summary = _category_summary(category_key, category_label, agent_items)
        if summary is None:
            continue
        seen_categories.add(category_key)
        summaries.append(summary)
    for item in agent_items:
        category_key = str(item.get("category_key") or "specialized")
        if category_key in seen_categories:
            continue
        summaries.append(
            {
                "category_key": category_key,
                "category_label": str(item.get("category_label") or "Specialized"),
                "is_core": False,
                "agent_count": 1,
                "agents": [item],
                "primary_agent_name": item.get("name") or "",
            }
        )
    return summaries


def _category_summary(
    category_key: str,
    category_label: str,
    agent_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    category_agents = [item for item in agent_items if item.get("category_key") == category_key]
    category_agents.sort(
        key=lambda item: (
            0
            if item.get("preference_status") == "primary"
            else 1
            if item.get("preference_status") != "hidden"
            else 2,
            -int(item.get("primary_score") or 0),
            str(item.get("name") or "").lower(),
        )
    )
    consolidation_candidates = [
        item["name"]
        for item in category_agents[1:]
        if category_agents
        and int(item.get("primary_score") or 0) <= int(category_agents[0].get("primary_score") or 0)
    ]
    if not category_agents:
        return None
    return {
        "category_key": category_key,
        "category_label": category_label,
        "is_core": category_key != "specialized",
        "agent_count": len(category_agents),
        "agents": category_agents,
        "primary_agent_name": category_agents[0]["name"],
        "primary_agent_id": category_agents[0]["id"],
        "consolidation_candidates": consolidation_candidates,
        "recommendation": f"Use {category_agents[0]['name']} as the default {category_label} entry point.",
    }
