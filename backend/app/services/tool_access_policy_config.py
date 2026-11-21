"""The Workspace tool policy as stored in a project config, read for the tool access decision.

``tool_access_policy`` decides whether one tool may run; this module only reads the
stored policy: the ``tool_policy`` block, the connector-disabled tools, and whether the
project is limited to read-only tools.
"""

from __future__ import annotations

from typing import Any

from .workflow_routing.tool_policy import normalized_tool_policy, tool_policy_has_allow_rules

READ_ONLY_TOOL_POLICY_VALUES = {"read_only", "read-only", "readonly", "viewer"}
READ_ONLY_PROJECT_ROLES = {"viewer", "support"}
READ_ONLY_GLOBAL_ROLES = {"support"}


def _normalize_string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item or "").strip() for item in value if str(item or "").strip()}


def _project_tool_policy(project_config: dict[str, Any] | None) -> dict[str, Any]:
    config = project_config if isinstance(project_config, dict) else {}
    policy = config.get("tool_policy")
    return dict(policy) if isinstance(policy, dict) else {}


def _project_tool_visibility_policy(project_config: dict[str, Any] | None) -> dict[str, Any]:
    policy = _project_tool_policy(project_config)
    connector_policy_disabled_tools = _connector_policy_disabled_tools(project_config)
    allowlist = sorted(_normalize_string_set(policy.get("allowlist")))
    denylist = [*_normalize_string_set(policy.get("denylist")), *connector_policy_disabled_tools]
    normalized = normalized_tool_policy(
        {
            "allowlist": allowlist,
            "denylist": denylist,
            "allow_patterns": policy.get("allow_patterns"),
            "deny_patterns": policy.get("deny_patterns"),
            "allow_read_only": policy.get("allow_read_only"),
            # Carried through so a grant counts next to visibility rules too: it
            # implies visibility and is the explicit allow a high-risk tool needs.
            "high_risk_grants": policy.get("high_risk_grants"),
        }
    )
    return normalized


def _connector_policy_disabled_tools(project_config: dict[str, Any] | None) -> set[str]:
    config = project_config if isinstance(project_config, dict) else {}
    connector_policies = config.get("connector_policies") if isinstance(config.get("connector_policies"), dict) else {}
    disabled_tools: set[str] = set()
    for policy in connector_policies.values():
        if not isinstance(policy, dict):
            continue
        disabled_tools.update(_normalize_string_set(policy.get("disabled_tools")))
    return disabled_tools


def project_tool_visibility_view(project_config: dict[str, Any] | None) -> dict[str, Any]:
    """The Workspace tool policy the dispatch enforces, for read-only display (settings review, finding 4).

    ``source`` is ``tool_policy`` when the project stores one, else ``none``; ``policy`` is the normalized effective
    visibility policy (connector-disabled tools included in the denylist).
    """
    config = project_config if isinstance(project_config, dict) else {}
    source = "tool_policy" if isinstance(config.get("tool_policy"), dict) else "none"
    policy = _project_tool_visibility_policy(config)
    return {"source": source, "policy": {key: sorted(value) if isinstance(value, list) else value
                                         for key, value in policy.items()}}


def project_tool_policy_has_allow_rules(project_config: dict[str, Any] | None) -> bool:
    """Whether the Workspace tool policy defines its tool surface (allowlist, allow patterns, read-only allow)."""

    return tool_policy_has_allow_rules(_project_tool_visibility_policy(project_config))


def project_enforces_read_only_tools(project_config: dict[str, Any] | None) -> bool:
    """Return whether the resolved project config requires read-only tools only."""

    config = project_config if isinstance(project_config, dict) else {}
    policy = _project_tool_policy(config)
    mode = str(policy.get("mode") or "").strip().lower()
    if mode in READ_ONLY_TOOL_POLICY_VALUES:
        return True
    if policy.get("read_only_tools_only") is True:
        return True
    if policy.get("allow_write_tools") is False:
        return True
    project_role = str(config.get("project_role") or "").strip().lower()
    if project_role in READ_ONLY_PROJECT_ROLES:
        return True
    roles = {str(role or "").strip().lower() for role in config.get("user_roles") or [] if str(role or "").strip()}
    if roles & READ_ONLY_GLOBAL_ROLES and not roles & {"admin", "operator"}:
        return True
    return False


__all__ = [
    "project_enforces_read_only_tools",
    "project_tool_policy_has_allow_rules",
    "project_tool_visibility_view",
]
