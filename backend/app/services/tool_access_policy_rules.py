"""The rules behind one project tool policy decision.

``tool_access_policy.tool_project_policy_decision`` picks the branch that applies
(visibility rules, read-only Workspace, high-risk tool without rules); this module
holds the decision record and the rules of each branch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .tool_access_policy_config import _normalize_string_set, _project_tool_policy
from .workflow_routing.tool_policy import (
    normalized_tool_policy,
    tool_name_is_allowed_by_policy,
    tool_name_matches_any_pattern,
)

# The refusal a per-call confirmation answers (chat connector writes); every other refusal stands.
HIGH_RISK_EXPLICIT_ALLOW_REASON = "high_risk_tool_requires_explicit_allow"

_READ_ONLY_EXTRA_DENYLIST = frozenset(
    {
        "bash",
        "run_cli_command",
        "run_kubectl",
        "run_kubectl_command",
        "run_saved_python_script",
        "call_mcp_server_tool",
        "set_context_checkpoint",
        "snapshot_create",
        "snapshot_restore",
        "freeze_context",
        "release_context",
        "worktree_create",
        "batch",
    }
)


@dataclass(frozen=True)
class ToolProjectPolicyDecision:
    tool_name: str
    allowed: bool
    policy: str
    reason: str
    error_message: str | None = None
    owner_type: str = "built_in"
    source: str = "base"
    risk: str = "read"
    required_config: str | None = None
    matched_rule: str | None = None
    requires_explicit_allow: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tool_requires_explicit_allow(metadata: Any) -> bool:
    if metadata.owner_type == "unknown" or metadata.risk == "unknown":
        return True
    return metadata.owner_type == "connector" and metadata.risk in {"write", "admin"}


def _tool_policy_explicitly_allows(tool_name: str, tool_policy: dict[str, Any] | None) -> str | None:
    """Explicit grant check for high-risk tools.

    Exact-name membership only: ``high_risk_grants`` is the dedicated grant
    list, and an exact ``allowlist`` name is an explicit allow as well.
    Visibility patterns and the read-only shortcut deliberately do NOT count —
    a broad ``allow_patterns: ["*"]`` must not silently unlock every
    high-risk connector tool.
    """
    normalized_name = str(tool_name or "").strip()
    policy = normalized_tool_policy(tool_policy)
    if normalized_name in set(policy["high_risk_grants"]):
        return "high_risk_grants"
    if normalized_name in set(policy["allowlist"]):
        return "allowlist"
    return None


def _decision(
    *,
    tool_name: str,
    allowed: bool,
    policy: str,
    reason: str,
    metadata: Any,
    error_message: str | None = None,
    matched_rule: str | None = None,
    requires_explicit_allow: bool = False,
) -> ToolProjectPolicyDecision:
    return ToolProjectPolicyDecision(
        tool_name=tool_name,
        allowed=allowed,
        policy=policy,
        reason=reason,
        error_message=error_message,
        owner_type=metadata.owner_type,
        source=metadata.source,
        risk=metadata.risk,
        required_config=metadata.required_config,
        matched_rule=matched_rule,
        requires_explicit_allow=requires_explicit_allow,
    )


def _visibility_denial(
    normalized_name: str,
    metadata: Any,
    visibility_policy: dict[str, Any],
    requires_explicit_allow: bool,
) -> ToolProjectPolicyDecision | None:
    """The visibility rule that refuses this tool, or ``None`` when the rules let it through."""
    if normalized_name in set(visibility_policy["denylist"]):
        return _decision(
            tool_name=normalized_name,
            allowed=False,
            policy="project_tool_policy",
            reason="denylist",
            metadata=metadata,
            error_message="Denied by the project tool visibility denylist.",
            matched_rule="denylist",
            requires_explicit_allow=requires_explicit_allow,
        )
    if any(
        tool_name_matches_any_pattern(normalized_name, [pattern])
        for pattern in visibility_policy["deny_patterns"]
    ):
        return _decision(
            tool_name=normalized_name,
            allowed=False,
            policy="project_tool_policy",
            reason="deny_patterns",
            metadata=metadata,
            error_message="Denied by a project tool visibility deny pattern.",
            matched_rule="deny_patterns",
            requires_explicit_allow=requires_explicit_allow,
        )
    if not tool_name_is_allowed_by_policy(normalized_name, visibility_policy):
        return _decision(
            tool_name=normalized_name,
            allowed=False,
            policy="project_tool_policy",
            reason="not_in_allow_rules",
            metadata=metadata,
            error_message="Not included in the project tool visibility allow rules.",
            matched_rule="allow_rules",
            requires_explicit_allow=requires_explicit_allow,
        )
    return None


def _visibility_decision(
    normalized_name: str,
    metadata: Any,
    visibility_policy: dict[str, Any],
    requires_explicit_allow: bool,
) -> ToolProjectPolicyDecision:
    """The decision of a Workspace whose tool policy has visibility rules."""
    denial = _visibility_denial(normalized_name, metadata, visibility_policy, requires_explicit_allow)
    if denial is not None:
        return denial
    explicit_match = _tool_policy_explicitly_allows(normalized_name, visibility_policy)
    if requires_explicit_allow and not explicit_match:
        return _decision(
            tool_name=normalized_name,
            allowed=False,
            policy="project_tool_policy_explicit_allow",
            reason=HIGH_RISK_EXPLICIT_ALLOW_REASON,
            metadata=metadata,
            error_message="High-risk tool requires an explicit project tool-policy allow rule.",
            requires_explicit_allow=True,
        )
    return _decision(
        tool_name=normalized_name,
        allowed=True,
        policy="project_tool_policy",
        reason="allowed_by_project_tool_policy",
        metadata=metadata,
        matched_rule=explicit_match,
        requires_explicit_allow=requires_explicit_allow,
    )


def _read_only_decision(
    normalized_name: str,
    metadata: Any,
    project_config: dict[str, Any] | None,
    requires_explicit_allow: bool,
) -> ToolProjectPolicyDecision:
    """The decision of a Workspace limited to read-only tools."""
    policy = _project_tool_policy(project_config)
    explicit_allowlist = _normalize_string_set(policy.get("read_only_allowlist"))
    if explicit_allowlist:
        allowed = normalized_name in explicit_allowlist
        return _decision(
            tool_name=normalized_name,
            allowed=allowed,
            policy="project_read_only_tools",
            reason="read_only_allowlist" if allowed else "not_in_read_only_allowlist",
            metadata=metadata,
            error_message=None if allowed else "Blocked by the project read-only tool policy.",
            matched_rule="read_only_allowlist",
            requires_explicit_allow=requires_explicit_allow,
        )
    explicit_denylist = _normalize_string_set(policy.get("read_only_denylist"))
    if normalized_name in explicit_denylist or normalized_name in _READ_ONLY_EXTRA_DENYLIST:
        return _decision(
            tool_name=normalized_name,
            allowed=False,
            policy="project_read_only_tools",
            reason="read_only_denylist",
            metadata=metadata,
            error_message="Blocked by the project read-only tool policy.",
            matched_rule="read_only_denylist",
            requires_explicit_allow=requires_explicit_allow,
        )
    allowed = not metadata.change_only
    return _decision(
        tool_name=normalized_name,
        allowed=allowed,
        policy="project_read_only_tools",
        reason="read_only_metadata" if allowed else "change_tool_in_read_only_project",
        metadata=metadata,
        error_message=None if allowed else "Blocked by the project read-only tool policy.",
        requires_explicit_allow=requires_explicit_allow,
    )


def _explicit_allow_decision(
    normalized_name: str,
    metadata: Any,
    project_config: dict[str, Any] | None,
) -> ToolProjectPolicyDecision:
    """A high-risk tool without visibility rules runs only on an explicit grant."""
    # A policy carrying only high_risk_grants has no visibility rules and
    # lands here — the grant must still count.
    explicit_match = _tool_policy_explicitly_allows(normalized_name, _project_tool_policy(project_config))
    if explicit_match:
        return _decision(
            tool_name=normalized_name,
            allowed=True,
            policy="project_tool_policy_explicit_allow",
            reason="allowed_by_high_risk_grant",
            metadata=metadata,
            matched_rule=explicit_match,
            requires_explicit_allow=True,
        )
    return _decision(
        tool_name=normalized_name,
        allowed=False,
        policy="project_tool_policy_explicit_allow",
        reason=HIGH_RISK_EXPLICIT_ALLOW_REASON,
        metadata=metadata,
        error_message="High-risk tool requires an explicit project tool-policy allow rule.",
        requires_explicit_allow=True,
    )


__all__ = [
    "HIGH_RISK_EXPLICIT_ALLOW_REASON",
    "ToolProjectPolicyDecision",
]
