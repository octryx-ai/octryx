"""Project-level access policy for MCP servers. Deny by default: a project must opt in before its sessions may list or
call a server's tools, resources or prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .data_classification.effect_rules import REASON_MCP_SERVER_OFF, mcp_server_off
from .model_gateway.data_policy.classification import (
    DATA_POLICY_CONFIG_KEY,
    declared_classification,
    resolve_data_classification,
)

MCP_POLICY_CONFIG_KEY = "mcp_policy"
ERROR_MCP_POLICY_INVALID = "mcp_policy_invalid"
_SERVER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_MAX_ITEMS = 200
REASON_MISSING_SERVER_NAME = "missing_server_name"
REASON_SERVER_DEACTIVATED = "explicit_server_deactivation"
REASON_SERVER_NOT_ACTIVE = "mcp_server_not_active_for_project"
DENIAL_REASONS = frozenset({REASON_MISSING_SERVER_NAME, REASON_MCP_SERVER_OFF, REASON_SERVER_DEACTIVATED,
                            REASON_SERVER_NOT_ACTIVE})


class McpPolicyError(ValueError):
    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.code = ERROR_MCP_POLICY_INVALID
        self.path = path


def _checked_names(value: Any, path: str, pattern: re.Pattern[str] | None = _SERVER) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > _MAX_ITEMS
        or any(not isinstance(item, str) or not item.strip() or (pattern and not pattern.match(item)) for item in value)
    ):
        raise McpPolicyError(path)
    return sorted(set(value))


def normalized_mcp_policy(value: Any) -> dict[str, Any]:
    allowed_keys = {"enabled_servers", "disabled_servers", "allow_all", "selected_tools"}
    if not isinstance(value, dict) or set(value) - allowed_keys:
        raise McpPolicyError(MCP_POLICY_CONFIG_KEY)
    policy: dict[str, Any] = {
        key: _checked_names(value.get(key, []), f"{MCP_POLICY_CONFIG_KEY}.{key}")
        for key in ("enabled_servers", "disabled_servers")
    }
    allow_all = value.get("allow_all", False)
    if type(allow_all) is not bool:
        raise McpPolicyError(f"{MCP_POLICY_CONFIG_KEY}.allow_all")
    policy["allow_all"] = allow_all
    selected = value.get("selected_tools")
    if selected is not None:
        if not isinstance(selected, dict) or len(selected) > _MAX_ITEMS:
            raise McpPolicyError(f"{MCP_POLICY_CONFIG_KEY}.selected_tools")
        policy["selected_tools"] = {
            _checked_names([server], f"{MCP_POLICY_CONFIG_KEY}.selected_tools")[0]: _checked_names(
                tools, f"{MCP_POLICY_CONFIG_KEY}.selected_tools.{server}", pattern=None
            )
            for server, tools in selected.items()
        }
    return policy


@dataclass(frozen=True, slots=True)
class McpServerAccessDecision:
    server_name: str
    allowed: bool
    reason: str

    def to_metadata(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "allowed": self.allowed,
            "reason": self.reason,
        }


def _normalized_names(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item or "").strip().lower() for item in value if str(item or "").strip()}


def effective_level(config: dict[str, Any], session_data_policy: Any = None) -> str | None:
    from app.services.knowledge.projection.workspace_classification_values import known_instance_default

    resolved = resolve_data_classification(
        project_data_policy=config.get(DATA_POLICY_CONFIG_KEY), session_data_policy=session_data_policy
    )
    if resolved.resolved:
        return resolved.classification
    return declared_classification(config.get(DATA_POLICY_CONFIG_KEY)) or known_instance_default()


def mcp_access_for_context(server_name: str | None, context: Any) -> McpServerAccessDecision:
    return mcp_server_access_decision(
        server_name, context.project_config, session_data_policy=getattr(context, "session_data_policy", None)
    )


def mcp_server_access_decision(
    server_name: str | None,
    project_config: dict[str, Any] | None,
    *,
    session_data_policy: Any = None,
) -> McpServerAccessDecision:
    normalized_server = str(server_name or "").strip()
    if not normalized_server:
        return McpServerAccessDecision(
            server_name="",
            allowed=False,
            reason=REASON_MISSING_SERVER_NAME,
        )
    config = project_config if isinstance(project_config, dict) else {}
    level = effective_level(config, session_data_policy)
    if level and mcp_server_off(normalized_server, level):
        # An added classification rule wins over the Workspace's own opt-in.
        return McpServerAccessDecision(server_name=normalized_server, allowed=False, reason=REASON_MCP_SERVER_OFF)
    policy = config.get(MCP_POLICY_CONFIG_KEY)
    policy = policy if isinstance(policy, dict) else {}
    lookup_name = normalized_server.lower()

    if lookup_name in _normalized_names(policy.get("disabled_servers")):
        return McpServerAccessDecision(
            server_name=normalized_server,
            allowed=False,
            reason=REASON_SERVER_DEACTIVATED,
        )
    if lookup_name in _normalized_names(policy.get("enabled_servers")):
        return McpServerAccessDecision(
            server_name=normalized_server,
            allowed=True,
            reason="explicit_server_activation",
        )
    if policy.get("allow_all") is True:
        return McpServerAccessDecision(
            server_name=normalized_server,
            allowed=True,
            reason="policy_allow_all",
        )
    return McpServerAccessDecision(
        server_name=normalized_server,
        allowed=False,
        reason=REASON_SERVER_NOT_ACTIVE,
    )


def selected_mcp_tools(server_name: str | None, project_config: dict[str, Any] | None) -> frozenset[str] | None:
    config = project_config if isinstance(project_config, dict) else {}
    policy = config.get(MCP_POLICY_CONFIG_KEY)
    selected = policy.get("selected_tools") if isinstance(policy, dict) else None
    if not isinstance(selected, dict):
        return None
    lookup = str(server_name or "").strip().lower()
    for name, tools in selected.items():
        if str(name).strip().lower() == lookup and isinstance(tools, list):
            return frozenset(str(tool).strip() for tool in tools if str(tool).strip())
    return None


def mcp_tool_allowed(server_name: str | None, tool_name: str | None, project_config: dict[str, Any] | None) -> bool:
    selected = selected_mcp_tools(server_name, project_config)
    return selected is None or str(tool_name or "").strip() in selected


def blocked_mcp_tool_result(server_name: str, tool_name: str) -> dict[str, Any]:
    return {
        "error": f"Tool '{tool_name}' of MCP server '{server_name}' is not selected for this Workspace.",
        "mcp_server": server_name,
        "blocked_by": "mcp_access_policy",
        "reason": "mcp_tool_not_selected",
    }


def blocked_mcp_server_result(decision: McpServerAccessDecision) -> dict[str, Any]:
    return {
        "error": (
            f"MCP server '{decision.server_name}' is not enabled for this project. "
            f"Enable it via the project's '{MCP_POLICY_CONFIG_KEY}' configuration."
        ),
        "mcp_server": decision.server_name,
        "blocked_by": "mcp_access_policy",
        "reason": decision.reason,
    }


__all__ = [
    "DENIAL_REASONS",
    "ERROR_MCP_POLICY_INVALID",
    "MCP_POLICY_CONFIG_KEY",
    "McpPolicyError",
    "McpServerAccessDecision",
    "blocked_mcp_server_result",
    "blocked_mcp_tool_result",
    "effective_level",
    "mcp_access_for_context",
    "mcp_server_access_decision",
    "mcp_tool_allowed",
    "normalized_mcp_policy",
    "selected_mcp_tools",
]
