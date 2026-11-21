"""Built-in connector configuration stored per project."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import BuiltInToolConfig
from ..connector_policy import list_connector_policies, normalize_connector_policy
from ..secret import resolve_secret_refs
from .connection_fields import global_config_for_scope, without_connection_identity
from .presets import TOOL_CONFIG_PRESETS
from .validation import validate_tool_config

_CONNECTOR_CREDENTIAL_BOUNDARY_TOOL_NAMES = {"bitbucket", "github", "gitlab"}


async def _project_config_for_tool_entry(db: AsyncSession, entry: BuiltInToolConfig) -> dict:
    if entry.tool_name in _CONNECTOR_CREDENTIAL_BOUNDARY_TOOL_NAMES:
        return dict(entry.config or {})
    return await resolve_secret_refs(
        db,
        entry.config,
        tool_name=entry.tool_name,
        project_id=entry.project_id,
    )


def _tool_description_map() -> dict[str, str]:
    from ...tools.registry import TOOL_REGISTRY

    return {tool_name: str(getattr(tool, "description", "") or "") for tool_name, tool in TOOL_REGISTRY.items()}


def _tool_catalog_metadata_map() -> dict[str, dict[str, Any]]:
    from ...tools.base import get_tool_capability_snapshot
    from ...tools.registry import TOOL_REGISTRY

    domain_map = _tool_definition_domain_map()
    metadata: dict[str, dict[str, Any]] = {}
    for tool_name, tool in TOOL_REGISTRY.items():
        capabilities = get_tool_capability_snapshot(tool)
        default_connector = get_default_connector_for_tool(tool_name)
        source_label = _derive_tool_source_label(tool, default_connector=default_connector)
        domain_label = domain_map.get(tool_name) or source_label
        metadata[tool_name] = {
            "read_only": capabilities.is_read_only,
            "concurrency_safe": capabilities.is_concurrency_safe,
            "enabled": capabilities.is_enabled,
            "source_label": source_label,
            "domain_label": domain_label,
        }
    return metadata


def _tool_definition_domain_map() -> dict[str, str]:
    from ...tools.definitions.getters import DEFINITION_GETTERS

    domain_map: dict[str, str] = {}
    for getter in DEFINITION_GETTERS:
        domain_label = _normalize_definition_domain_label(getter.__module__.split(".")[-1])
        if not domain_label:
            continue
        for tool_name in getter().keys():
            domain_map[tool_name] = domain_label
    return domain_map


def _normalize_definition_domain_label(module_name: str) -> str | None:
    normalized = str(module_name or "").strip().lower()
    if not normalized or normalized.startswith("everything_else_"):
        return None
    if normalized.startswith("get_") and normalized.endswith("_definitions"):
        normalized = normalized[4:-12]
    if normalized.endswith("_definitions"):
        normalized = normalized[:-12]
    return normalized or None


def _derive_tool_source_label(tool: Any, *, default_connector: str | None) -> str | None:
    if default_connector:
        return f"connector:{default_connector}"

    module_name = type(tool).__module__
    for marker, label in (
        (".connectors.", "connector"),
        (".admin_impl.", "admin"),
        (".knowledge_impl.", "knowledge"),
        (".office_impl.", "office"),
        (".code_impl.", "workspace"),
        (".runtime_impl.", "runtime"),
    ):
        if marker in module_name:
            return label

    suffix = module_name.split(".")[-1]
    if suffix in {
        "browser",
        "context_tools",
        "confluence",
        "diagram",
        "documents",
        "grafana",
        "kubernetes",
        "loki",
        "lsp",
        "mcp_bridge",
        "prometheus",
        "python_runtime",
        "session_tools",
        "sub_agent",
        "worktree",
    }:
        return suffix
    return None


def get_default_connector_for_tool(tool_name: str) -> str | None:
    matches: list[str] = []
    for connector_name, preset in TOOL_CONFIG_PRESETS.items():
        for tool in preset.get("tools", []):
            if tool.get("name") == tool_name:
                matches.append(connector_name)
                break
    return matches[0] if len(matches) == 1 else None


def get_tool_catalog() -> list[dict[str, Any]]:
    from ...tools.definitions import get_tool_definition_metadata

    descriptions = _tool_description_map()
    metadata_map = _tool_catalog_metadata_map()
    entries: list[dict[str, Any]] = []
    for tool_name in sorted(descriptions.keys()):
        default_connector = get_default_connector_for_tool(tool_name)
        metadata = metadata_map.get(tool_name, {})
        tool_def_metadata = get_tool_definition_metadata(tool_name)
        entry: dict[str, Any] = {
            "name": tool_name,
            "description": descriptions.get(tool_name, ""),
            "default_connector": default_connector,
            "is_core": tool_def_metadata.is_core,
            "change_only": tool_def_metadata.change_only,
            "plan_excluded": tool_def_metadata.plan_excluded,
            "plan_only": tool_def_metadata.plan_only,
        }
        entry.update(metadata)
        entries.append(entry)
    return entries


def resolve_connector_tools(connector_name: str, policy: dict | None = None) -> list[dict[str, str]]:
    preset = TOOL_CONFIG_PRESETS.get(connector_name, {})
    catalog = get_tool_catalog()
    catalog_by_name = {item["name"]: item for item in catalog}
    built_in_names = [tool.get("name") for tool in preset.get("tools", []) if tool.get("name")]
    extra_tools = [
        tool_name
        for tool_name in (policy or {}).get("extra_tools", []) or []
        if isinstance(tool_name, str) and tool_name in catalog_by_name
    ]
    disabled_tools = {
        tool_name for tool_name in (policy or {}).get("disabled_tools", []) or [] if isinstance(tool_name, str)
    }
    effective_names: list[str] = []
    for tool_name in [*built_in_names, *extra_tools]:
        if tool_name in disabled_tools or tool_name in effective_names:
            continue
        effective_names.append(tool_name)
    descriptions = _tool_description_map()
    return [{"name": tool_name, "description": descriptions.get(tool_name, "")} for tool_name in effective_names]


async def list_tool_configs(db: AsyncSession, project_id: str | None = None) -> list[BuiltInToolConfig]:
    stmt = select(BuiltInToolConfig).order_by(BuiltInToolConfig.tool_name.asc())
    if project_id is None:
        stmt = stmt.where(BuiltInToolConfig.project_id.is_(None))
    else:
        stmt = stmt.where(BuiltInToolConfig.project_id == project_id)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_tool_config(db: AsyncSession, tool_name: str, project_id: str | None = None) -> BuiltInToolConfig | None:
    stmt = select(BuiltInToolConfig).where(BuiltInToolConfig.tool_name == tool_name)
    if project_id is None:
        stmt = stmt.where(BuiltInToolConfig.project_id.is_(None))
    else:
        stmt = stmt.where(BuiltInToolConfig.project_id == project_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_tool_config(
    db: AsyncSession,
    *,
    tool_name: str,
    project_id: str | None,
    config: dict,
    description: str = "",
    is_active: bool = True,
) -> BuiltInToolConfig:
    validated_config = validate_tool_config(tool_name, config)
    entry = await get_tool_config(db, tool_name, project_id)
    if not entry:
        entry = BuiltInToolConfig(tool_name=tool_name, project_id=project_id)
        db.add(entry)

    entry.config = validated_config
    entry.description = description.strip() or None
    entry.is_active = is_active
    await db.flush()
    return entry


async def merge_tool_configs_into_project_config(db: AsyncSession, project_id: str | None, config: dict) -> dict:
    # A connection comes only from the tool entries, never from Project.config.
    merged = without_connection_identity(config)

    global_configs = await list_tool_configs(db, None)
    if not project_id:
        for entry in global_configs:
            if entry.is_active and entry.config:
                merged.update(await _project_config_for_tool_entry(db, entry))
    else:
        global_by_name = {entry.tool_name: entry for entry in global_configs}
        project_configs = await list_tool_configs(db, project_id)
        for project_entry in project_configs:
            if not project_entry.is_active:
                continue
            global_entry = global_by_name.get(project_entry.tool_name)
            if global_entry and global_entry.is_active and global_entry.config:
                # The credential unit is never mixed across scopes (connection_fields.py).
                global_config = await _project_config_for_tool_entry(db, global_entry)
                merged.update(global_config_for_scope(project_entry.tool_name, global_config, project_entry.config))
            if project_entry.config:
                merged.update(await _project_config_for_tool_entry(db, project_entry))
    policy_entries = [
        *(await list_connector_policies(db, None)),
        *((await list_connector_policies(db, project_id)) if project_id else []),
    ]
    connector_policies: dict[str, dict] = {}
    for entry in policy_entries:
        if entry.is_active:
            connector_policies[entry.connector_name] = normalize_connector_policy(entry.policy if entry.policy else {})
    if connector_policies:
        merged["connector_policies"] = connector_policies
    await _attach_named_connections(db, project_id, merged)
    return merged


async def _attach_named_connections(db: AsyncSession, project_id: str | None, merged: dict) -> None:
    """The connections the Workspace may use, for the tool router; never a value from
    ``Project.config``. The default connection's unit replaces its entry's (``unbound_default.py``); the platform
    scope (no Workspace) has no connection routes."""
    from app.services.named_connections.routes_model import NAMED_CONNECTIONS_KEY
    from app.services.named_connections.workspace_routes import workspace_routes

    from ..named_connections.unbound_default import apply_defaults

    merged.pop(NAMED_CONNECTIONS_KEY, None)
    if not project_id:
        return
    # Secrets are resolved per call, for the one connection that serves it (tool_routing.py).
    routes = await workspace_routes(db, project_id, secrets=False)
    if routes.defaults:
        replaced = await apply_defaults(db, merged, routes)
        merged.clear()
        merged.update(replaced)
    if routes.connections or routes.defaults or routes.ambiguous:
        merged[NAMED_CONNECTIONS_KEY] = routes


def build_tool_config_forms(
    entries: list[BuiltInToolConfig],
    project_id: str | None,
    test_results: dict[str, dict] | None = None,
) -> list[dict]:
    entry_map = {entry.tool_name: entry for entry in entries}
    test_results = test_results or {}
    forms = []
    for tool_name, preset in TOOL_CONFIG_PRESETS.items():
        entry = entry_map.get(tool_name)
        config = entry.config if entry and entry.config else preset["example"]
        secret_fields = preset.get("secret_fields", [])
        public_config = {
            key: value for key, value in config.items() if key not in secret_fields and not key.endswith("_secret_ref")
        }
        secret_refs = {
            field_name: config.get(f"{field_name}_secret_ref")
            for field_name in secret_fields
            if config.get(f"{field_name}_secret_ref")
        }
        forms.append(
            {
                "tool_name": tool_name,
                "label": preset["label"],
                "description": preset["description"],
                "fields": preset["fields"],
                "project_id": project_id or "",
                "config_json": json.dumps(public_config, indent=2),
                "is_active": entry.is_active if entry else True,
                "entry": entry,
                "description_value": entry.description if entry and entry.description else "",
                "secret_fields": secret_fields,
                "secret_refs": secret_refs,
                "supports_connection_test": tool_name
                in {
                    "jira",
                    "bitbucket",
                    "confluence",
                    "kubernetes",
                    "vault",
                    "sonarqube",
                    "snyk",
                    "ansible",
                    "datadog",
                    "newrelic",
                    "aws",
                    "azure",
                    "gcp",
                    "statuspage",
                    "helm",
                    "docker_registry",
                    "splunk",
                    "linear",
                    "azure_devops",
                },
                "test_result": test_results.get(tool_name),
            }
        )
    return forms


__all__ = [
    "TOOL_CONFIG_PRESETS",
    "validate_tool_config",
    "get_default_connector_for_tool",
    "get_tool_catalog",
    "resolve_connector_tools",
    "list_tool_configs",
    "get_tool_config",
    "upsert_tool_config",
    "merge_tool_configs_into_project_config",
    "build_tool_config_forms",
]
