"""Canonical chat launch capability surface for bootstrap and send contracts."""

from __future__ import annotations

from typing import Any


def build_chat_launch_surface(
    *,
    user_roles: list[str],
    project_options: list[dict[str, str]],
) -> dict[str, Any]:
    normalized_roles = sorted({str(role or "").strip().lower() for role in user_roles if str(role or "").strip()})
    allowed_project_ids = [str(project.get("id") or "").strip() for project in project_options if project.get("id")]

    return {
        "version": 1,
        "role_scope": "admin" if "admin" in normalized_roles else "standard",
        "role_names": normalized_roles,
        "primary_controls": ["runtime", "project", "thinking"],
        "advanced_controls": [],
        "explicit_choices": ["runtime", "project", "thinking"],
        "derived_choices": ["mode", "agent_group", "agent"],
        "hidden_choices": ["mode", "agent_group", "agent"],
        "allow_advanced_overrides": False,
        "allow_mode_override": False,
        "allow_agent_override": False,
        "allow_agent_group_override": False,
        "allowed_project_ids": allowed_project_ids,
    }


__all__ = ["build_chat_launch_surface"]
