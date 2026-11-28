"""Run capability each tool needs: ``read_only``, ``change`` or ``deliver``."""

from __future__ import annotations

from .definitions import get_tool_definition_metadata
from .definitions.rest_tool_classes import rest_write_class
from .definitions.write_risk import BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES, PLATFORM_ADMIN_WRITE_DEFINITION_NAMES

CAPABILITY_READ_ONLY = "read_only"
CAPABILITY_CHANGE = "change"
CAPABILITY_DELIVER = "deliver"

# Write-risk tools that stay inside read-only runs; each group comment gives the reason.
_READ_ONLY_COMPATIBLE_WRITE_TOOL_NAMES = frozenset(
    {
        # Platform-owned state: the Knowledge Memory lobe and platform-native tasks.
        "memory_remember",
        "work_item_create",
        "work_item_link_session",
        "work_item_note",
        # The chat's work-item lifecycle is platform state; a mapped Jira transition is the platform's own sync.
        "change_plan_decide",
        "change_plan_generate",
        "change_units_plan",
        "coding_agent_start",
        "work_item_redeclare",
        "work_item_transition",
        # Agent coordination is platform state; a takeover is still confirmed by a person (or the auto policy).
        "board_ack",
        "board_post",
        "work_item_claim",
        "work_item_handoff_write",
        "work_item_release",
        "work_item_takeover_request",
        # Run steering: the run's current phase class bounds what an action may do.
        "workflow_action_request",
        "workflow_decide",
        "workflow_select",
        # Rating an answer like the chat's thumbs: session feedback, platform state.
        "knowledge_feedback",
        # Not ``workspace_select``: Terraform's ``workspace new`` creates remote backend state, so it needs ``deliver``.
        # Fresh checkouts into the session workspace, required by read-only code-structure and knowledge workflows.
        "prepare_bitbucket_repository",
        "prepare_github_repository",
        "prepare_gitlab_repository",
        "collect_repository_knowledge_sources",
        # The security analyzer checks every command per run capability (read-only runs keep the diagnosis rules).
        "run_cli_command",
        "start_runtime_process",
        "cancel_runtime_process",
    }
)

# Read-risk metadata that nonetheless changes the session workspace or runs builds.
_WORKSPACE_CHANGE_READ_RISK_TOOL_NAMES = frozenset(
    {
        "run_openrewrite_recipe",
        "run_test_suite",
    }
)

# Built-in write tools that leave the platform boundary (browser actions, outbound HTTP), plus platform admin writes.
_BUILT_IN_DELIVER_TOOL_NAMES = frozenset(
    {
        "http_request",
        *BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES,
        *PLATFORM_ADMIN_WRITE_DEFINITION_NAMES,
    }
)

_EXTERNAL_OWNER_TYPES = frozenset({"connector", "mcp", "dynamic_database", "dynamic_rest"})


def is_known_tool(tool_name: str) -> bool:
    return get_tool_definition_metadata(str(tool_name or "").strip()).owner_type != "unknown"


def tool_required_capability(tool_name: str) -> str:
    name = str(tool_name or "").strip()
    metadata = get_tool_definition_metadata(name)
    if metadata.risk == "unknown" or metadata.owner_type == "unknown":
        return CAPABILITY_DELIVER
    if metadata.risk == "admin":
        # Admin reads (listings, diagnostics) are reads; admin writes change the platform.
        return CAPABILITY_DELIVER if metadata.change_only else CAPABILITY_READ_ONLY
    if metadata.risk != "write":
        return CAPABILITY_CHANGE if name in _WORKSPACE_CHANGE_READ_RISK_TOOL_NAMES else CAPABILITY_READ_ONLY
    if name in _READ_ONLY_COMPATIBLE_WRITE_TOOL_NAMES:
        return CAPABILITY_READ_ONLY
    if metadata.owner_type == "dynamic_rest":
        # A custom REST write needs ``deliver`` (an external write) unless its admin declared it ``change``.
        return rest_write_class(name) or CAPABILITY_DELIVER
    if metadata.owner_type in _EXTERNAL_OWNER_TYPES or name in _BUILT_IN_DELIVER_TOOL_NAMES:
        return CAPABILITY_DELIVER
    return CAPABILITY_CHANGE


# A read_only run requires the selected MCP capability's binding risk (``policy_config["risk"]``) to be ``read``.
_MCP_RISK_REQUIRED_CAPABILITY = {
    "read": CAPABILITY_READ_ONLY,
    "unknown": CAPABILITY_CHANGE,
    "write": CAPABILITY_DELIVER,
    "admin": CAPABILITY_DELIVER,
}


def mcp_capability_required_class(risk: str) -> str:
    return _MCP_RISK_REQUIRED_CAPABILITY.get(str(risk or "").strip().lower(), CAPABILITY_CHANGE)


__all__ = [
    "CAPABILITY_CHANGE",
    "CAPABILITY_DELIVER",
    "CAPABILITY_READ_ONLY",
    "mcp_capability_required_class",
    "tool_required_capability",
]
