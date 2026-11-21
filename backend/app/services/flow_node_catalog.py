from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BuiltInToolConfig, Project, User
from ..tools.base import get_tool_capability_snapshot
from ..tools.definitions import get_all_definitions, get_tool_definition_metadata
from ..tools.definitions.connector_ownership import SERVICE_ONLY_TOOLS
from ..tools.registry import TOOL_REGISTRY
from ..tools.visibility import connector_activation_decision
from .flow_node_catalog_describe import (
    _connector_for_tool,
    _display_name,
    _generic_audit_behavior,
    _generic_cost_risk,
    _generic_evidence_behavior,
    _node_type_for_tool,
    _tool_category,
    _tool_config_schema,
    _tool_cost_risk,
    _tool_description,
    _tool_evidence_behavior,
    _tool_permission_requirements,
)
from .flow_node_registry import serialize_flow_node_registry
from .project.service import get_project_config
from .tool_access_policy import explain_tool_project_policy_denial
from .tool_config import TOOL_CONFIG_PRESETS

Availability = str


async def build_flow_node_catalog(
    db: AsyncSession,
    *,
    project_id: str | None,
    current_user: User,
    include_disabled: bool = True,
) -> dict[str, Any]:
    """Build the governed Flow Builder node catalog for a project."""

    normalized_project_id = str(project_id or "").strip() or None
    project = await _get_project(db, normalized_project_id)
    project_config = await get_project_config(normalized_project_id, db)
    connector_state = await _load_connector_state(db, normalized_project_id)

    generic_items = _generic_catalog_items()
    tool_items = _tool_catalog_items(
        project_id=normalized_project_id,
        project_config=project_config,
        connector_state=connector_state,
        include_disabled=include_disabled,
    )
    items = [*generic_items, *tool_items]
    return {
        "schema_version": "1.0",
        "project_id": normalized_project_id,
        "project_name": project.name if project else "Global",
        "user_id": current_user.id,
        "include_disabled": include_disabled,
        "items": items,
        "counts": {
            "total": len(items),
            "available": sum(1 for item in items if item["availability_status"] == "available"),
            "disabled": sum(1 for item in items if item["availability_status"] == "disabled"),
        },
    }


async def _get_project(db: AsyncSession, project_id: str | None) -> Project | None:
    if not project_id:
        return None
    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def _load_connector_state(db: AsyncSession, project_id: str | None) -> dict[str, dict[str, Any]]:
    result = await db.execute(select(BuiltInToolConfig).order_by(BuiltInToolConfig.tool_name.asc()))
    rows = result.scalars().all()
    global_entries = {row.tool_name: row for row in rows if row.project_id is None}
    project_entries = {row.tool_name: row for row in rows if project_id and row.project_id == project_id}
    state: dict[str, dict[str, Any]] = {}
    for connector_name in sorted(set(TOOL_CONFIG_PRESETS) | set(global_entries) | set(project_entries)):
        global_entry = global_entries.get(connector_name)
        project_entry = project_entries.get(connector_name)
        state[connector_name] = {
            "global_configured": bool(global_entry),
            "global_active": bool(global_entry and global_entry.is_active),
            "project_configured": bool(project_entry),
            "project_enabled": bool(project_entry and project_entry.is_active),
        }
    return state


def _generic_catalog_items() -> list[dict[str, Any]]:
    registry = serialize_flow_node_registry()
    items: list[dict[str, Any]] = []
    for contract in registry["items"]:
        items.append(
            {
                "id": f"node:{contract['type']}",
                "node_type": contract["type"],
                "binding_type": "generic",
                "binding_ref": contract["type"],
                "display_name": contract["display_name"],
                "category": contract["category"],
                "icon_hint": contract["type"],
                "description": contract["description"],
                "config_schema": contract.get("config_schema") or {},
                "input_schema": contract.get("input_schema") or {},
                "output_schema": contract.get("output_schema") or {},
                "availability_status": "available",
                "disabled_reason": None,
                "permission_requirements": list(contract.get("security_requirements") or []),
                "token_cost_risk": _generic_cost_risk(contract),
                "evidence_behavior": _generic_evidence_behavior(contract),
                "audit_behavior": _generic_audit_behavior(contract),
                "default_config": {},
            }
        )
    return items


def _tool_catalog_items(
    *,
    project_id: str | None,
    project_config: dict[str, Any],
    connector_state: dict[str, dict[str, Any]],
    include_disabled: bool,
) -> list[dict[str, Any]]:
    definitions = get_all_definitions()
    items: list[dict[str, Any]] = []
    for tool_name in sorted(TOOL_REGISTRY):
        definition = definitions.get(tool_name)
        if not definition or tool_name in SERVICE_ONLY_TOOLS:
            continue
        disabled_reason = _tool_disabled_reason(tool_name, project_id, project_config, connector_state)
        if disabled_reason and not include_disabled:
            continue
        capability = get_tool_capability_snapshot(TOOL_REGISTRY[tool_name])
        metadata = get_tool_definition_metadata(tool_name)
        connector_name = _connector_for_tool(tool_name)
        category = _tool_category(tool_name, connector_name)
        items.append(
            {
                "id": f"tool:{tool_name}",
                "node_type": _node_type_for_tool(tool_name, category),
                "binding_type": "tool",
                "binding_ref": tool_name,
                "display_name": _display_name(tool_name),
                "category": category,
                "icon_hint": connector_name or "tool",
                "description": _tool_description(definition, tool_name),
                "config_schema": _tool_config_schema(tool_name, definition),
                "input_schema": {"arguments": "object"},
                "output_schema": {"result": "object"},
                "availability_status": "disabled" if disabled_reason else "available",
                "disabled_reason": disabled_reason,
                "permission_requirements": _tool_permission_requirements(
                    tool_name,
                    connector_name=connector_name,
                    read_only=capability.is_read_only,
                ),
                "token_cost_risk": _tool_cost_risk(tool_name, read_only=capability.is_read_only),
                "evidence_behavior": _tool_evidence_behavior(tool_name, category),
                "audit_behavior": (
                    "Tool calls are recorded in the session trace with parameters, result summary, and policy context."
                ),
                "default_config": {"tool": tool_name},
                "metadata": {
                    "connector_name": connector_name,
                    "read_only": capability.is_read_only,
                    "concurrency_safe": capability.is_concurrency_safe,
                    "enabled": capability.is_enabled,
                    "change_only": metadata.change_only,
                    "plan_excluded": metadata.plan_excluded,
                    "plan_only": metadata.plan_only,
                    "is_core": metadata.is_core,
                },
            }
        )
    return items


def _tool_disabled_reason(
    tool_name: str,
    project_id: str | None,
    project_config: dict[str, Any],
    connector_state: dict[str, dict[str, Any]],
) -> str | None:
    policy_reason = explain_tool_project_policy_denial(tool_name, project_config)
    if policy_reason:
        return policy_reason
    connector_name = _connector_for_tool(tool_name)
    if not connector_name or connector_name not in TOOL_CONFIG_PRESETS:
        return None
    state = connector_state.get(connector_name, {})
    if project_id and state.get("project_enabled") and connector_activation_decision(connector_name, project_config)[0]:
        # The Workspace's own or named connection serves it (the tool router's activation), global entry or not.
        return None
    if not state.get("global_configured"):
        return f"{connector_name} connector is not globally configured."
    if not state.get("global_active"):
        return f"{connector_name} connector is globally disabled."
    if project_id and not state.get("project_configured"):
        return f"{connector_name} connector is configured globally but not granted to this project."
    if project_id and not state.get("project_enabled"):
        return f"{connector_name} connector grant is disabled for this project."
    return None


__all__ = ["build_flow_node_catalog"]
