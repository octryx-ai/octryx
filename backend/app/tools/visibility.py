"""Project-scoped tool visibility decisions.

Connector tools are enterprise capability boundaries. They must not be shown to
the model, or executed directly, unless the current project activates the owning
connector. This module keeps that decision centralized so runtime, discovery and
dispatch agree.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..services.classification_tool_policy import POLICY_NAME as CLASSIFICATION_POLICY_NAME
from ..services.classification_tool_policy import classification_tool_decision, classification_tool_refusal
from .connector_activation_catalog import COMPOSITE_CONNECTOR_MEMBERS, CONNECTOR_ALIASES, CONNECTOR_CONFIG_KEYS
from .definitions import get_tool_definition_metadata
from .definitions.connector_ownership import SERVICE_ONLY_TOOLS

_TRUE_VALUES = {"1", "true", "yes", "on", "enabled", "active"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled", "inactive"}
CONNECTION_GRANT_POLICY = "connection_grant"
SERVICE_ONLY_POLICY = "service_only_connector"

@dataclass(frozen=True)
class ToolVisibilityDecision:
    tool_name: str
    visible: bool
    reason: str
    owner_type: str
    source: str
    connector: str | None = None
    required_config: str | None = None
    policy: str = "connector_activation"
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_name(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _connector_aliases(connector: str) -> set[str]:
    normalized = _normalize_name(connector)
    return {normalized, *(CONNECTOR_ALIASES.get(normalized) or set())}


def _bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


def _value_has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_value_has_content(item) for item in value)
    if isinstance(value, dict):
        explicit_enabled = _explicit_enabled_value(value)
        if explicit_enabled is False:
            return False
        if explicit_enabled is True:
            return True
        return any(_value_has_content(item) for item in value.values())
    return True


def _explicit_enabled_value(value: dict[str, Any]) -> bool | None:
    for key in ("enabled", "is_enabled", "active", "is_active", "tools_enabled", "tool_enabled"):
        if key in value:
            return _bool_value(value.get(key))
    return None


def _connector_name_from_item(item: dict[str, Any]) -> str:
    for key in ("connector", "connector_name", "provider", "provider_type", "tool_name", "name", "id"):
        raw = item.get(key)
        normalized = _normalize_name(raw)
        if normalized:
            return normalized
    return ""


def _connector_matches(candidate: Any, connector: str) -> bool:
    normalized_candidate = _normalize_name(candidate)
    if not normalized_candidate:
        return False
    return normalized_candidate in _connector_aliases(connector)


def _explicit_connector_activation(connector: str, config: dict[str, Any]) -> tuple[bool | None, str | None]:
    aliases = _connector_aliases(connector)

    for key in ("disabled_connectors", "inactive_connectors"):
        value = config.get(key)
        if isinstance(value, list) and any(_connector_matches(item, connector) for item in value):
            return False, key

    for key in ("enabled_connectors", "active_connectors"):
        value = config.get(key)
        if isinstance(value, list) and any(_connector_matches(item, connector) for item in value):
            return True, key

    for key in (
        "connector_activation",
        "connector_visibility",
        "connector_tool_visibility",
        "connector_status",
        "connectors",
    ):
        value = config.get(key)
        if isinstance(value, dict):
            for candidate, raw_state in value.items():
                if not _connector_matches(candidate, connector):
                    continue
                if isinstance(raw_state, dict):
                    explicit = _explicit_enabled_value(raw_state)
                    if explicit is not None:
                        return explicit, f"{key}.{candidate}"
                    return _value_has_content(raw_state), f"{key}.{candidate}"
                explicit = _bool_value(raw_state)
                if explicit is not None:
                    return explicit, f"{key}.{candidate}"
        elif isinstance(value, list):
            matched_without_state = False
            for item in value:
                if isinstance(item, dict):
                    item_name = _connector_name_from_item(item)
                    if not item_name or item_name not in aliases:
                        continue
                    explicit = _explicit_enabled_value(item)
                    if explicit is not None:
                        return explicit, f"{key}.{item_name}"
                    matched_without_state = True
                    continue
                if _connector_matches(item, connector):
                    return True, key
            if matched_without_state:
                return True, key

    for alias in aliases:
        for suffix in ("enabled", "active"):
            key = f"{alias}_{suffix}".replace("-", "_")
            if key in config:
                explicit = _bool_value(config.get(key))
                if explicit is not None:
                    return explicit, key
        for prefix in ("enable", "activate"):
            key = f"{prefix}_{alias}".replace("-", "_")
            if key in config:
                explicit = _bool_value(config.get(key))
                if explicit is not None:
                    return explicit, key

    return None, None


def _named_connection_evidence(connector: str, config: dict[str, Any]) -> str | None:
    """``named_connection:<id>`` when a Workspace or global named connection serves the connector."""
    from ..services.named_connections.resolver import serving_connection

    for alias in sorted(_connector_aliases(connector)):
        connection = serving_connection(config, alias)
        if connection is not None:
            return f"named_connection:{connection.id}"
    return None


def connector_activation_decision(
    connector: str | None,
    project_config: dict[str, Any] | None,
) -> tuple[bool, str, str | None]:
    normalized_connector = _normalize_name(connector)
    if not normalized_connector:
        return False, "missing_connector_metadata", None

    config = project_config if isinstance(project_config, dict) else {}
    explicit, evidence = _explicit_connector_activation(normalized_connector, config)
    if explicit is not None:
        reason = "explicit_connector_activation" if explicit else "explicit_connector_deactivation"
        return explicit, reason, evidence

    for key in CONNECTOR_CONFIG_KEYS.get(normalized_connector, ()):
        if _value_has_content(config.get(key)):
            return True, "project_connector_config_present", key

    served = _named_connection_evidence(normalized_connector, config)
    if served is not None:
        return True, "named_connection_in_scope", served

    for member in COMPOSITE_CONNECTOR_MEMBERS.get(normalized_connector, ()):
        member_active, _member_reason, member_evidence = connector_activation_decision(member, config)
        if member_active:
            return True, "member_connector_active", f"{member}:{member_evidence}"

    return False, "connector_not_active_for_project", f"connector:{normalized_connector}"


def tool_visibility_decision(tool_name: str, project_config: dict[str, Any] | None) -> ToolVisibilityDecision:
    normalized_name = str(tool_name or "").strip()
    metadata = get_tool_definition_metadata(normalized_name)
    if normalized_name in SERVICE_ONLY_TOOLS:
        return ToolVisibilityDecision(
            tool_name=normalized_name, visible=False, reason=SERVICE_ONLY_POLICY, owner_type=metadata.owner_type,
            source=metadata.source, connector=metadata.connector, required_config=metadata.required_config,
            policy=SERVICE_ONLY_POLICY, evidence=f"connector:{metadata.connector}",
        )
    # The Workspace's classification level narrows first; arguments are checked at dispatch.
    classification = classification_tool_decision(normalized_name, project_config)
    if not classification.allowed:
        return ToolVisibilityDecision(
            tool_name=normalized_name, visible=False, reason=classification.reason,
            owner_type=metadata.owner_type, source=metadata.source, connector=classification.family,
            required_config=metadata.required_config, policy=CLASSIFICATION_POLICY_NAME,
            evidence=f"classification:{classification.level}",
        )
    if metadata.owner_type != "connector":
        return ToolVisibilityDecision(
            tool_name=normalized_name,
            visible=True,
            reason="non_connector_tool",
            owner_type=metadata.owner_type,
            source=metadata.source,
            connector=metadata.connector,
            required_config=metadata.required_config,
        )

    active, reason, evidence = connector_activation_decision(metadata.connector, project_config)
    hidden = _connection_grant_refusal(normalized_name, project_config) if active else None
    if hidden is not None:
        # No connection that could serve the tool allows it (agent tools level, disabled).
        active, reason, evidence = False, hidden, f"connection_grant:{hidden}"
    return ToolVisibilityDecision(
        tool_name=normalized_name,
        visible=active,
        reason=reason,
        owner_type=metadata.owner_type,
        source=metadata.source,
        connector=metadata.connector,
        required_config=metadata.required_config,
        evidence=evidence,
        policy=CONNECTION_GRANT_POLICY if hidden is not None else "connector_activation",
    )


def _connection_grant_refusal(tool_name: str, config: dict[str, Any] | None) -> str | None:
    from ..services.named_connections.connection_gate import hidden_reason

    return hidden_reason(tool_name, config)


def tool_is_visible_for_project(tool_name: str, project_config: dict[str, Any] | None) -> bool:
    return tool_visibility_decision(tool_name, project_config).visible


def filter_tool_definitions_by_visibility(
    tool_definitions: list[dict[str, Any]],
    project_config: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for definition in tool_definitions:
        function = definition.get("function") if isinstance(definition, dict) else None
        tool_name = str((function or {}).get("name") or "").strip() if isinstance(function, dict) else ""
        if tool_is_visible_for_project(tool_name, project_config):
            filtered.append(definition)
    return filtered


def blocked_inactive_connector_tool_result(
    tool_name: str,
    project_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    decision = tool_visibility_decision(tool_name, project_config)
    if decision.visible:
        return None
    if decision.policy == CLASSIFICATION_POLICY_NAME:
        return classification_tool_refusal(tool_name, project_config, None)
    if decision.policy == SERVICE_ONLY_POLICY:
        return {"error": f"Tool '{decision.tool_name}' serves platform services only and is not offered to agents.",
                "code": SERVICE_ONLY_POLICY, "tool_name": decision.tool_name, "policy": SERVICE_ONLY_POLICY,
                "visibility_decision": decision.to_dict()}
    if decision.policy == CONNECTION_GRANT_POLICY:
        return {"error": f"No connection of this Workspace allows tool '{decision.tool_name}' ({decision.reason}).",
                "code": decision.reason, "state": "needs_configuration", "tool_name": decision.tool_name,
                "policy": CONNECTION_GRANT_POLICY, "visibility_decision": decision.to_dict()}
    return {
        "error": (
            f"Connector '{decision.connector or 'unknown'}' is not active for this project; "
            f"tool '{decision.tool_name}' is not available."
        ),
        "tool_name": decision.tool_name,
        "policy": "connector_activation",
        "visibility_decision": decision.to_dict(),
    }


__all__ = [
    "ToolVisibilityDecision",
    "blocked_inactive_connector_tool_result",
    "connector_activation_decision",
    "filter_tool_definitions_by_visibility",
    "tool_is_visible_for_project",
    "tool_visibility_decision",
]
