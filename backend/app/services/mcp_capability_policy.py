"""Per-capability access policy for mirrored MCP tools.

``services/mcp_access_policy.py`` decides whether a project may talk to an MCP
*server* at all. This module is the second, narrower gate: once a server is
active, each individual capability still needs an enabled Workspace Capability
binding (``CapabilityType(kind="mcp_capability")`` +
``WorkspaceCapabilityBinding``) before it may be listed or executed.

Decision rules, in order:

- no database session or no resolvable workspace id → ``unverifiable`` → deny
- no binding for the tool → deny (``mcp_capability_not_bound``). Mirroring a server's catalog creates a
  disabled binding per tool; an admin enables it in the Workspace capability catalog, which is the only way a
  newly registered tool becomes usable
- a binding exists → allow only when the binding is enabled, visible, its capability type is still active, and
  its argument contract is not waiting for a schema-drift review

An allowed capability still goes through the tool approval policy before it runs.

Server identity is case-insensitive everywhere, exactly like
``mcp_access_policy``: ``normalized_mcp_server_name`` casefolds the server for
every catalog key, index key, and lookup, so a case variant of a server name
always finds the same binding. Tool names stay
case-sensitive because the remote server owns them.

Risk and scopes are metadata only: ``policy_config["risk"]`` and
``intent_scopes`` on the binding. Nothing is ever inferred from a capability's
name or description.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import WorkspaceCapabilityBinding

MCP_CAPABILITY_KIND = "mcp_capability"
MCP_CAPABILITY_SOURCE_ENTITY_TYPE = "mcp_server_tool"
MCP_CAPABILITY_POLICY_NAME = "mcp_capability_policy"
MCP_CAPABILITY_RISKS = ("read", "write", "admin", "unknown")
DEFAULT_MCP_CAPABILITY_RISK = "unknown"
# A capability whose mirrored argument contract changed stays denied until an
# admin reviews it, so drift can never widen an already approved contract.
MCP_CAPABILITY_REVIEW_STATE_NEEDS_REVIEW = "needs_review"

_HIDDEN_BINDING_STATUS = "hidden"


def normalized_mcp_server_name(server_name: Any) -> str:
    """Return the canonical, case-insensitive identity of one MCP server.

    ``mcp_access_policy`` already matches server names case-insensitively, so
    capability identity must too: mirror, index, and lookup all go through this
    function and therefore agree on what "the same server" means.
    """
    return str(server_name or "").strip().casefold()


def mcp_capability_binding_key(server_name: str, tool_name: str) -> str:
    """Return the deterministic catalog key for one remote MCP capability."""
    return f"mcp-capability:{normalized_mcp_server_name(server_name)}:{str(tool_name or '').strip()}"


def mcp_capability_subject_key(server_name: str, tool_name: str) -> str:
    """Return the approval/dispatch identity shared by every execution path."""
    return f"mcp__{normalized_mcp_server_name(server_name)}__{str(tool_name or '').strip()}"


def normalized_mcp_capability_risk(value: Any) -> str:
    """Return an explicit, allow-listed risk; unknown metadata stays ``unknown``."""
    risk = str(value or "").strip().lower()
    return risk if risk in MCP_CAPABILITY_RISKS else DEFAULT_MCP_CAPABILITY_RISK


@dataclass(frozen=True, slots=True)
class MirroredMcpCapability:
    """The governance-relevant projection of one mirrored capability binding."""

    server_name: str
    tool_name: str
    binding_key: str
    binding_status: str
    is_enabled: bool
    capability_type_active: bool
    risk: str
    scopes: tuple[str, ...]
    schema_digest: str
    review_state: str = ""


@dataclass(frozen=True, slots=True)
class McpCapabilityIndex:
    """One workspace's mirrored MCP catalog, loaded once per gate evaluation."""

    workspace_id: str
    capabilities: Mapping[tuple[str, str], MirroredMcpCapability] = field(default_factory=dict)

    def get(self, server_name: str, tool_name: str) -> MirroredMcpCapability | None:
        return self.capabilities.get((normalized_mcp_server_name(server_name), str(tool_name or "").strip()))


def _binding_capability(binding: WorkspaceCapabilityBinding) -> MirroredMcpCapability | None:
    binding_config = binding.binding_config if isinstance(binding.binding_config, dict) else {}
    policy_config = binding.policy_config if isinstance(binding.policy_config, dict) else {}
    server_name = normalized_mcp_server_name(binding_config.get("serverName"))
    tool_name = str(binding_config.get("toolName") or "").strip()
    if not server_name or not tool_name:
        return None
    capability_type = binding.capability_type
    return MirroredMcpCapability(
        server_name=server_name,
        tool_name=tool_name,
        binding_key=str(binding.binding_key or ""),
        binding_status=str(binding.binding_status or "").strip().lower(),
        is_enabled=bool(binding.is_enabled),
        capability_type_active=bool(getattr(capability_type, "is_active", False)),
        risk=normalized_mcp_capability_risk(policy_config.get("risk")),
        scopes=tuple(str(scope).strip() for scope in (binding.intent_scopes or []) if str(scope).strip()),
        schema_digest=str(binding_config.get("schemaDigest") or ""),
        review_state=str(binding_config.get("reviewState") or "").strip().lower(),
    )


async def load_mcp_capability_index(db: AsyncSession, *, workspace_id: str) -> McpCapabilityIndex:
    """Load every mirrored MCP capability for one workspace in a single query."""
    normalized_workspace_id = str(workspace_id or "").strip()
    if not normalized_workspace_id:
        return McpCapabilityIndex(workspace_id="")
    rows = (
        (
            await db.execute(
                select(WorkspaceCapabilityBinding)
                .options(selectinload(WorkspaceCapabilityBinding.capability_type))
                .where(
                    WorkspaceCapabilityBinding.workspace_id == normalized_workspace_id,
                    WorkspaceCapabilityBinding.capability_kind == MCP_CAPABILITY_KIND,
                )
            )
        )
        .scalars()
        .all()
    )
    capabilities: dict[tuple[str, str], MirroredMcpCapability] = {}
    for row in rows:
        capability = _binding_capability(row)
        if capability is not None:
            capabilities[(capability.server_name, capability.tool_name)] = capability
    return McpCapabilityIndex(workspace_id=normalized_workspace_id, capabilities=capabilities)


__all__ = [
    "DEFAULT_MCP_CAPABILITY_RISK",
    "MCP_CAPABILITY_KIND",
    "MCP_CAPABILITY_POLICY_NAME",
    "MCP_CAPABILITY_REVIEW_STATE_NEEDS_REVIEW",
    "MCP_CAPABILITY_RISKS",
    "MCP_CAPABILITY_SOURCE_ENTITY_TYPE",
    "McpCapabilityIndex",
    "MirroredMcpCapability",
    "load_mcp_capability_index",
    "mcp_capability_binding_key",
    "mcp_capability_subject_key",
    "normalized_mcp_capability_risk",
    "normalized_mcp_server_name",
]
