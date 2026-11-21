"""Project-scoped connector access: whether a Workspace uses a connector, and its allowlists/limits.

The access save merges into the Workspace's tool config entry: it sets ``is_active`` and
replaces only the allowlist/limit fields. The Workspace's own connection (URL, auth mode,
principals, secret refs; ``workspace_connection_service.py``) is never touched by it, and never
re-validated either: only the fields this save changes are validated, so an entry the connection save would now
refuse keeps saving access. A refusal is a coded 422.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import BuiltInToolConfig, ConnectorNamedConnection, Project
from ...tool_config import (
    TOOL_CONFIG_PRESETS,
    get_tool_config,
    list_tool_configs,
    validate_tool_config,
)

CODE_ACCESS_INVALID = "connector_access_invalid"
# An own Confluence/Jira connection can be set up from scratch, without any entry; source control is
# usually a Workspace's own account (Bitbucket Cloud, GitHub, GitLab), so it can be switched on without a global entry.
ALWAYS_LISTED = ("confluence", "jira", "bitbucket", "github", "gitlab")

_PROJECT_SCOPE_FIELDS = {
    "outlook_absence_mailboxes",
    "sharepoint_site_paths",
}


def _is_project_limit_field(field_name: str) -> bool:
    normalized = str(field_name or "").strip()
    return "allowed" in normalized or normalized in _PROJECT_SCOPE_FIELDS


PROJECT_CONNECTOR_LIMIT_FIELDS: dict[str, tuple[str, ...]] = {
    connector_name: tuple(
        field_name for field_name in preset.get("fields", []) if _is_project_limit_field(str(field_name))
    )
    for connector_name, preset in TOOL_CONFIG_PRESETS.items()
}

PROJECT_CONNECTOR_NAMES = tuple(PROJECT_CONNECTOR_LIMIT_FIELDS.keys())


async def list_project_connector_access(db: AsyncSession, *, project_id: str) -> dict[str, Any]:
    await _require_project(db, project_id)
    global_entries = {entry.tool_name: entry for entry in await list_tool_configs(db, None)}
    project_entries = {entry.tool_name: entry for entry in await list_tool_configs(db, project_id)}
    connector_names = sorted(
        {
            entry.tool_name
            for entry in [*global_entries.values(), *project_entries.values()]
            if entry.tool_name in TOOL_CONFIG_PRESETS
        }
        | {name for name in ALWAYS_LISTED if name in TOOL_CONFIG_PRESETS}
        # A connector this Workspace (or the platform) has named connections for is always listed.
        | {name for name in await _named_connectors(db, project_id) if name in TOOL_CONFIG_PRESETS}
    )
    connectors = []
    for connector_name in connector_names:
        global_entry = global_entries.get(connector_name)
        project_entry = project_entries.get(connector_name)
        global_config = dict(global_entry.config or {}) if global_entry else {}
        project_config = dict(project_entry.config or {}) if project_entry else {}
        limit_fields = PROJECT_CONNECTOR_LIMIT_FIELDS.get(connector_name, ())
        # Only limits that restrict something count: an empty list is no limit.
        project_limits = {field: project_config[field] for field in limit_fields if _has_value(project_config.get(field))}
        inherited_limits = {field: global_config[field] for field in limit_fields if _has_value(global_config.get(field))}
        preset = TOOL_CONFIG_PRESETS.get(connector_name, {})
        connectors.append(
            {
                "connector_name": connector_name,
                "label": str(preset.get("label") or connector_name.title()),
                "description": str(preset.get("description") or ""),
                "limit_fields": list(limit_fields),
                "global_configured": bool(global_entry),
                "global_active": bool(global_entry and global_entry.is_active),
                "project_enabled": bool(project_entry and project_entry.is_active),
                "project_configured": bool(project_entry),
                "project_limits": project_limits,
                "inherited_limits": inherited_limits,
                "effective_limits": project_limits or inherited_limits,
                "inherits_global_limits": not bool(project_limits),
            }
        )
    return {"project_id": project_id, "connectors": connectors}


MAX_BATCH_WORKSPACES = 200


async def connector_limits_in_workspaces(db: AsyncSession, *, connector_name: str, project_ids: list[str],
                                         user_id: str) -> dict[str, Any]:
    """One connector's limits (``project_limits``, the global ``inherited_limits``) in several Workspaces at once.

    Reading every Workspace's whole connector list for a connection's "Today, unbound" view runs many requests in
    parallel with two pooled connections each; with the page's other reads that can exhaust the API's database pool
    and take the API out of service. Two queries, one connection, the same values as
    :func:`list_project_connector_access`. Unknown Workspaces and somebody else's private ones are left out (the
    per-Workspace route answers 404 for those; ``private_workspace_gate`` checks only one named id)."""
    from ...project.private_workspace import hidden_private_ids

    if connector_name not in TOOL_CONFIG_PRESETS:
        raise HTTPException(status_code=404, detail="Unknown connector")
    wanted = list(dict.fromkeys(str(item) for item in project_ids if str(item).strip()))[:MAX_BATCH_WORKSPACES]
    limit_fields = PROJECT_CONNECTOR_LIMIT_FIELDS.get(connector_name, ())
    known = set((await db.execute(select(Project.id).where(Project.id.in_(wanted or [""])))).scalars().all())
    known -= set(await hidden_private_ids(db, user_id))
    rows = (await db.execute(select(BuiltInToolConfig).where(
        BuiltInToolConfig.tool_name == connector_name,
        or_(BuiltInToolConfig.project_id.is_(None), BuiltInToolConfig.project_id.in_(wanted or [""]))))).scalars().all()
    by_project = {row.project_id: dict(row.config or {}) for row in rows}
    global_config = by_project.get(None, {})
    return {
        "connector_name": connector_name,
        "limit_fields": list(limit_fields),
        "inherited_limits": {field: global_config[field] for field in limit_fields
                             if _has_value(global_config.get(field))},
        "workspaces": [{"project_id": project_id, "project_limits": {
            field: by_project.get(project_id, {})[field] for field in limit_fields
            if _has_value(by_project.get(project_id, {}).get(field))}} for project_id in wanted if project_id in known],
    }


async def update_project_connector_access(
    db: AsyncSession,
    *,
    project_id: str,
    connector_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _require_project(db, project_id)
    normalized_connector = str(connector_name or "").strip().lower()
    if normalized_connector not in TOOL_CONFIG_PRESETS:
        raise HTTPException(status_code=404, detail="Unknown project connector")
    is_active = bool(payload.get("is_active", False))
    limits = _project_limit_config(normalized_connector, payload.get("limits") if isinstance(payload, dict) else {})
    # Merge, never replace. Everything but the limit fields (the Workspace's own connection)
    # stays exactly as stored; the limits are replaced as a whole by what this save sends.
    existing = await get_tool_config(db, normalized_connector, project_id)
    limit_fields = set(PROJECT_CONNECTOR_LIMIT_FIELDS.get(normalized_connector, ()))
    config = {
        key: value
        for key, value in (dict(existing.config or {}) if existing else {}).items()
        if key not in limit_fields
    }
    try:
        # Only what this save changes; messages name fields, never values.
        validate_tool_config(normalized_connector, limits)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": CODE_ACCESS_INVALID, "message": str(exc)}) from None
    config.update(limits)
    if existing is None:
        existing = BuiltInToolConfig(tool_name=normalized_connector, project_id=project_id)
        db.add(existing)
    existing.config = config
    existing.description = "Project connector access grant"
    existing.is_active = is_active
    await db.commit()
    return await list_project_connector_access(db, project_id=project_id)


async def _named_connectors(db: AsyncSession, project_id: str) -> set[str]:
    rows = await db.execute(select(ConnectorNamedConnection.tool_name).where(
        or_(ConnectorNamedConnection.project_id == project_id, ConnectorNamedConnection.project_id.is_(None))))
    return set(rows.scalars())


async def _require_project(db: AsyncSession, project_id: str) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _project_limit_config(connector_name: str, raw_limits: Any) -> dict[str, Any]:
    limits = raw_limits if isinstance(raw_limits, dict) else {}
    allowed_fields = PROJECT_CONNECTOR_LIMIT_FIELDS.get(connector_name, ())
    config: dict[str, Any] = {}
    for field in allowed_fields:
        value = limits.get(field)
        if value in (None, "", []):
            continue
        config[field] = value
    return config


__all__ = [
    "PROJECT_CONNECTOR_LIMIT_FIELDS",
    "PROJECT_CONNECTOR_NAMES",
    "connector_limits_in_workspaces",
    "list_project_connector_access",
    "update_project_connector_access",
]
