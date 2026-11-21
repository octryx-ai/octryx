"""Connector activation state and the runtime-visible tool catalog derived from it."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....tools.definitions import get_tool_definition_metadata
from ....tools.visibility import connector_activation_decision, tool_visibility_decision
from ...connector_policy import list_connector_policies, normalize_connector_policy
from ...tool_config import TOOL_CONFIG_PRESETS, get_tool_catalog, list_tool_configs

_DEFAULT_ACTIVE_CONNECTORS = {"system"}


@dataclass(frozen=True, slots=True)
class ConnectorActivationState:
    connector_name: str
    is_active: bool
    is_configured: bool
    is_runtime_visible: bool
    reason: str
    runtime_connector: str | None = None
    runtime_visibility_reason: str | None = None
    runtime_visibility_evidence: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _tool_connector_names(connector_policies: dict[str, dict[str, Any]] | None = None) -> dict[str, set[str]]:
    tool_connectors: dict[str, set[str]] = {}
    for connector_name, preset in TOOL_CONFIG_PRESETS.items():
        for tool in preset.get("tools", []):
            tool_name = str(tool.get("name") or "").strip()
            if tool_name:
                tool_connectors.setdefault(tool_name, set()).add(connector_name)
    for connector_name, policy in (connector_policies or {}).items():
        for tool_name in policy.get("extra_tools") or []:
            normalized_tool_name = str(tool_name or "").strip()
            if normalized_tool_name:
                tool_connectors.setdefault(normalized_tool_name, set()).add(connector_name)
    return tool_connectors


def _is_connector_only_catalog_entry(entry: dict[str, Any], connector_names: set[str]) -> bool:
    if not connector_names:
        return False
    source_label = str(entry.get("source_label") or "").strip()
    return not source_label or source_label == "connector" or source_label.startswith("connector:")


def _runtime_connector_names_for_preset(connector_name: str, preset: dict[str, Any]) -> tuple[str, ...]:
    names: set[str] = set()
    for tool in preset.get("tools", []):
        tool_name = str(tool.get("name") or "").strip()
        if not tool_name:
            continue
        metadata = get_tool_definition_metadata(tool_name)
        if metadata.connector:
            names.add(metadata.connector)
    return tuple(sorted(names or {connector_name}))


def _connector_runtime_visibility(
    *,
    connector_name: str,
    config: dict[str, Any],
    preset: dict[str, Any],
) -> tuple[bool, str, str | None, str | None]:
    for runtime_connector in _runtime_connector_names_for_preset(connector_name, preset):
        active, reason, evidence = connector_activation_decision(runtime_connector, config)
        if active:
            return True, reason, evidence, runtime_connector
    runtime_connector = next(iter(_runtime_connector_names_for_preset(connector_name, preset)), connector_name)
    return False, "connector_not_active_for_project", None, runtime_connector


def _connector_has_effective_config(*, connector_name: str, config: dict[str, Any], preset: dict[str, Any]) -> bool:
    fields = list(preset.get("fields") or [])
    if not fields:
        return True
    visible, _reason, _evidence, _runtime_connector = _connector_runtime_visibility(
        connector_name=connector_name,
        config=config,
        preset=preset,
    )
    return visible


def _non_default_activation_state(
    connector_name: str,
    entry: Any | None,
    *,
    is_configured: bool,
    runtime_visible: bool,
    runtime_reason: str,
    runtime_evidence: str | None,
    runtime_connector: str | None,
) -> ConnectorActivationState:
    if not entry:
        return ConnectorActivationState(
            connector_name=connector_name,
            is_active=False,
            is_configured=False,
            is_runtime_visible=False,
            reason="missing_configuration",
            runtime_connector=runtime_connector,
            runtime_visibility_reason=runtime_reason,
            runtime_visibility_evidence=runtime_evidence,
        )
    if not entry.is_active:
        return ConnectorActivationState(
            connector_name=connector_name,
            is_active=False,
            is_configured=is_configured,
            is_runtime_visible=False,
            reason="connector_disabled",
            runtime_connector=runtime_connector,
            runtime_visibility_reason="explicit_connector_deactivation",
        )
    if not is_configured:
        return ConnectorActivationState(
            connector_name=connector_name,
            is_active=True,
            is_configured=False,
            is_runtime_visible=False,
            reason="needs_configuration",
            runtime_connector=runtime_connector,
            runtime_visibility_reason=runtime_reason,
            runtime_visibility_evidence=runtime_evidence,
        )
    return ConnectorActivationState(
        connector_name=connector_name,
        is_active=True,
        is_configured=True,
        is_runtime_visible=runtime_visible,
        reason="configured_active",
        runtime_connector=runtime_connector,
        runtime_visibility_reason=runtime_reason,
        runtime_visibility_evidence=runtime_evidence,
    )


def _build_activation_state(connector_name: str, entry: Any | None, preset: dict[str, Any]) -> ConnectorActivationState:
    is_active = bool(entry.is_active) if entry else connector_name in _DEFAULT_ACTIVE_CONNECTORS
    config = dict(entry.config) if entry and entry.config else {}
    runtime_visible, runtime_reason, runtime_evidence, runtime_connector = _connector_runtime_visibility(
        connector_name=connector_name,
        config=config,
        preset=preset,
    )
    is_configured = _connector_has_effective_config(connector_name=connector_name, config=config, preset=preset)

    if connector_name in _DEFAULT_ACTIVE_CONNECTORS and is_active:
        return ConnectorActivationState(
            connector_name=connector_name,
            is_active=True,
            is_configured=True,
            is_runtime_visible=True,
            reason="default_active",
            runtime_connector=connector_name,
            runtime_visibility_reason="default_active",
        )
    return _non_default_activation_state(
        connector_name,
        entry,
        is_configured=is_configured,
        runtime_visible=runtime_visible,
        runtime_reason=runtime_reason,
        runtime_evidence=runtime_evidence,
        runtime_connector=runtime_connector,
    )


def list_connector_activation_states(entries: list[Any]) -> list[dict[str, Any]]:
    entry_map = {entry.tool_name: entry for entry in entries}
    return [
        _build_activation_state(connector_name, entry_map.get(connector_name), preset).to_payload()
        for connector_name, preset in TOOL_CONFIG_PRESETS.items()
    ]


def _active_connector_names(entries: list[Any]) -> set[str]:
    states = list_connector_activation_states(entries)
    return {state["connector_name"] for state in states if state["is_runtime_visible"]}


def build_connector_runtime_project_config(entries: list[Any]) -> dict[str, Any]:
    """Build a secret-free project-config snapshot for runtime visibility checks."""

    entry_map = {entry.tool_name: entry for entry in entries}
    runtime_config: dict[str, Any] = {}
    disabled_runtime_connectors: list[str] = []
    for state in list_connector_activation_states(entries):
        connector_name = str(state.get("connector_name") or "").strip()
        if not connector_name or connector_name in _DEFAULT_ACTIVE_CONNECTORS:
            continue
        entry = entry_map.get(connector_name)
        if state.get("is_runtime_visible") and entry and entry.config:
            runtime_config.update(dict(entry.config))
        elif state.get("reason") == "connector_disabled" and state.get("runtime_connector"):
            disabled_runtime_connectors.append(str(state["runtime_connector"]))
    if disabled_runtime_connectors:
        runtime_config["disabled_connectors"] = sorted(set(disabled_runtime_connectors))
    return runtime_config


async def list_tool_catalog_payload(db: AsyncSession) -> list[dict[str, Any]]:
    config_entries = await list_tool_configs(db, None)
    active_connectors = _active_connector_names(config_entries)
    policy_entries = await list_connector_policies(db, None)
    active_connector_policies = {
        entry.connector_name: normalize_connector_policy(entry.policy if entry.policy else {})
        for entry in policy_entries
        if entry.is_active
    }
    runtime_project_config = build_connector_runtime_project_config(config_entries)
    if active_connector_policies:
        runtime_project_config["connector_policies"] = active_connector_policies
    tool_connectors = _tool_connector_names(active_connector_policies)
    visible_entries: list[dict[str, Any]] = []
    for raw_entry in get_tool_catalog():
        entry = dict(raw_entry)
        if entry.get("enabled") is False:
            continue
        tool_name = str(entry.get("name") or "").strip()
        connector_names = tool_connectors.get(tool_name, set())
        active_entry_connectors = sorted(connector_names.intersection(active_connectors))
        disabled_entry_connectors = sorted(
            connector_name
            for connector_name in active_entry_connectors
            if tool_name in set(active_connector_policies.get(connector_name, {}).get("disabled_tools") or [])
        )
        active_entry_connectors = [
            connector_name
            for connector_name in active_entry_connectors
            if connector_name not in disabled_entry_connectors
        ]
        runtime_visibility = tool_visibility_decision(tool_name, runtime_project_config)
        if _is_connector_only_catalog_entry(entry, connector_names):
            if not active_entry_connectors:
                continue
            if not runtime_visibility.visible:
                continue
            entry["connectors"] = [name for name in active_entry_connectors if name not in _DEFAULT_ACTIVE_CONNECTORS]
        else:
            entry["connectors"] = []
        entry["runtime_visibility"] = runtime_visibility.to_dict()
        entry["connector_visibility"] = {
            "active_connectors": active_entry_connectors,
            "disabled_connectors": disabled_entry_connectors,
        }
        visible_entries.append(entry)
    return visible_entries
