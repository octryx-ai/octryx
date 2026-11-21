"""Run capability each tool needs: ``read_only``, ``change`` or ``deliver``.

A workflow definition declares one capability class (``services/run_capability``) and
a run may only dispatch tools whose requirement fits inside it. The requirement is
derived from the tool's canonical metadata (``definitions.get_tool_definition_metadata``:
risk, owner, change-only flag) plus the closed exception tables below, never from a
tool's name pattern or description.

- ``read_only``: reads, and writes to platform-owned state that neither edits the
  session workspace nor reaches an external system (memory, platform work items),
  source materialization for investigation (a fresh
  checkout of a connector repository), and command execution tools whose individual
  commands are governed by the security analyzer per capability.
- ``change``: edits files in the session workspace, runs builds and tests, local
  commits and worktrees.
- ``deliver``: pushes, pull requests, writes to external systems through connectors,
  outbound HTTP writes, and platform administration writes.

Unknown tools need ``deliver`` (fail closed): no class short of it may dispatch them.
"""

from __future__ import annotations

from .definitions import get_tool_definition_metadata
from .definitions.rest_tool_classes import rest_write_class
from .definitions.write_risk import BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES, PLATFORM_ADMIN_WRITE_DEFINITION_NAMES

CAPABILITY_READ_ONLY = "read_only"
CAPABILITY_CHANGE = "change"
CAPABILITY_DELIVER = "deliver"

# Write-risk tools that stay inside read-only runs. Each entry is a deliberate
# decision; the reason is the group comment.
_READ_ONLY_COMPATIBLE_WRITE_TOOL_NAMES = frozenset(
    {
        # Platform-owned state: the Knowledge Memory lobe and platform-native tasks.
        "memory_remember",
        "work_item_create",
        "work_item_link_session",
        "work_item_note",
        # The client's work-item lifecycle in the chat: plans, decisions, transitions and the
        # start of a governed coding run are platform state; a mapped Jira transition is the platform's own sync.
        "change_plan_decide",
        "change_plan_generate",
        "change_units_plan",
        "coding_agent_start",
        "work_item_redeclare",
        "work_item_transition",
        # Coordination between agents: claims, board posts, handoffs and takeover requests are
        # platform state; a takeover is still confirmed by a person in the UI (or the Workspace's auto policy).
        "board_ack",
        "board_post",
        "work_item_claim",
        "work_item_handoff_write",
        "work_item_release",
        "work_item_takeover_request",
        # The client's run steering: a decision or action for the run this chat follows; the run's
        # current phase class bounds what an action may do (``workflow_runs/octryx/actions``).
        "workflow_action_request",
        "workflow_decide",
        "workflow_select",
        # Rating an answer like the chat's thumbs: session feedback, platform state.
        "knowledge_feedback",
        # Not ``workspace_select``: it is Terraform's ``workspace select/new`` (connector-owned),
        # and ``new`` creates state in the remote backend, so it needs ``deliver``.
        # Source materialization for investigation: a fresh checkout into the session
        # workspace, required by read-only code-structure and knowledge workflows.
        "prepare_bitbucket_repository",
        "prepare_github_repository",
        "prepare_gitlab_repository",
        "collect_repository_knowledge_sources",
        # Command execution: every command is analyzed per run capability by the
        # security analyzer (read-only runs keep the diagnosis command rules).
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

# Built-in (non-connector) write tools that leave the platform boundary (browser
# page interactions, outbound HTTP), and platform administration writes.
_BUILT_IN_DELIVER_TOOL_NAMES = frozenset(
    {
        "http_request",
        *BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES,
        *PLATFORM_ADMIN_WRITE_DEFINITION_NAMES,
    }
)

_EXTERNAL_OWNER_TYPES = frozenset({"connector", "mcp", "dynamic_database", "dynamic_rest"})


def is_known_tool(tool_name: str) -> bool:
    """True when a built-in, connector, database, REST, MCP or plugin tool of this name exists."""
    return get_tool_definition_metadata(str(tool_name or "").strip()).owner_type != "unknown"


def tool_required_capability(tool_name: str) -> str:
    """The minimum run capability class that may dispatch ``tool_name``."""
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


# The class one remote MCP capability needs, from the risk an admin assigned to its Workspace binding
# (``mcp_capability_policy``: ``policy_config["risk"]``, mirrored as ``unknown``). The bridge tools themselves are
# static reads, so without this a write capability of a foreign server ran inside a read_only run, held back only by
# the approval policy. Only a capability classified ``read`` stays read_only;
# an unclassified one may change but not deliver, and a write or admin capability reaches an external system.
_MCP_RISK_REQUIRED_CAPABILITY = {
    "read": CAPABILITY_READ_ONLY,
    "unknown": CAPABILITY_CHANGE,
    "write": CAPABILITY_DELIVER,
    "admin": CAPABILITY_DELIVER,
}


def mcp_capability_required_class(risk: str) -> str:
    """The minimum run class for an MCP capability of ``risk``; an unlisted risk counts as ``unknown``."""
    return _MCP_RISK_REQUIRED_CAPABILITY.get(str(risk or "").strip().lower(), CAPABILITY_CHANGE)


__all__ = [
    "CAPABILITY_CHANGE",
    "CAPABILITY_DELIVER",
    "CAPABILITY_READ_ONLY",
    "mcp_capability_required_class",
    "tool_required_capability",
]
