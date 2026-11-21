"""Project access role names: validation, merging and the role-based assignments in project config."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from ....models import Project

PROJECT_ACCESS_ROLE_RE = re.compile(r"^[a-z][a-z0-9_-]{1,49}$")
PROJECT_ROLE_ASSIGNMENTS_CONFIG_KEY = "role_access_assignments"
DEFAULT_PROJECT_ACCESS_ROLE = "member"


def _normalize_project_role(value: Any) -> str:
    role = str(value or DEFAULT_PROJECT_ACCESS_ROLE).strip().lower()
    if not PROJECT_ACCESS_ROLE_RE.fullmatch(role):
        raise HTTPException(
            status_code=400,
            detail="Project access role must be 2-50 lowercase characters and may contain numbers, '_' or '-'.",
        )
    return role


def _normalize_project_roles(value: Any, *, allow_default: bool = True) -> list[str]:
    if value is None:
        return [DEFAULT_PROJECT_ACCESS_ROLE]
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        role = _normalize_project_role(item)
        if role in seen:
            continue
        seen.add(role)
        normalized.append(role)

    if not normalized:
        return [DEFAULT_PROJECT_ACCESS_ROLE] if allow_default else []
    return normalized


def _extract_project_roles(raw_roles: Any, fallback: str | None) -> list[str]:
    roles = _normalize_project_roles(raw_roles, allow_default=False)
    if not roles and fallback:
        return [fallback]
    if not roles:
        return [DEFAULT_PROJECT_ACCESS_ROLE]
    return roles


def _normalize_role_identifier(value: Any) -> str:
    return str(value or "").strip()


def _normalize_global_role_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _merge_project_roles(current_roles: list[str], extra_roles: list[str]) -> list[str]:
    seen = set(current_roles)
    merged = list(current_roles)
    for role in extra_roles:
        if role in seen:
            continue
        merged.append(role)
        seen.add(role)
    return merged


def _serialize_role_assignments(
    project: Project,
    roles_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    if not isinstance(project.config, dict):
        return []

    raw = project.config.get(PROJECT_ROLE_ASSIGNMENTS_CONFIG_KEY)
    if not isinstance(raw, list):
        return []

    normalized_roles: dict[str, list[str]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        role_id = _normalize_role_identifier(item.get("role_id"))
        if not role_id:
            role_name = _normalize_global_role_name(item.get("role"))
            role_id = next(
                (rid for rid, name in roles_by_id.items() if _normalize_global_role_name(name) == role_name),
                "",
            )
        if not role_id or role_id not in roles_by_id:
            continue
        normalized_roles[role_id] = _merge_project_roles(
            normalized_roles.get(role_id, []),
            _extract_project_roles(
                item.get("project_roles"),
                DEFAULT_PROJECT_ACCESS_ROLE,
            ),
        )

    return [
        {
            "role_id": role_id,
            "role": roles_by_id[role_id],
            "project_roles": normalized_roles[role_id],
            "project_role": normalized_roles[role_id][0],
            "granted_by": None,
            "granted_at": None,
        }
        for role_id in sorted(normalized_roles, key=lambda rid: roles_by_id[rid].lower())
    ]
