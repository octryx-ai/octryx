"""Mirror discovered MCP tools into the Workspace Capability catalog.

This follows the established catalog-mirror pattern of
``workspace_composition.sync_workspace_runtime_catalog_bindings``: a globally
registered capability becomes a ``CapabilityType`` plus a **disabled** workspace
binding, so mirroring never widens a project's execution surface by itself.

Only the normalized public contract built by ``mcp_capability_contract`` is
persisted. MCP connection configuration — commands, URLs, environment, headers,
OAuth material — is never read here and never stored.

Re-mirroring is idempotent. It refreshes the capability type contract and the
binding's schema digest and never rewrites admin-owned governance state
(``policy_config``, ``is_enabled``, ``is_default``, ``intent_scopes``,
``binding_status``) — with one deliberate exception: when a capability's
argument contract drifted from the one an admin approved, the binding is
parked in an explicit ``reviewState="needs_review"`` deny state and
disabled until an admin re-enables it (see
``acknowledged_mcp_capability_schema_config``, applied by the admin write path in
``mcp_capability_admin_policy``).

A re-mirror also never reactivates a globally retired ``CapabilityType``:
``is_active`` is set once at creation and is owned by the catalog lifecycle
afterwards. Re-running the mirror can therefore only refresh a contract, never
widen execution; retired capabilities are reported back as
``inactive_capabilities``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CapabilityType, WorkspaceCapabilityBinding
from ..time_utils import utc_now
from .mcp_capability_contract import (
    capability_display_name,
    discovered_mcp_tools,
    exceeds_mcp_identifier_limits,
    mcp_capability_contract,
    server_identifier_error,
)
from .mcp_capability_mirror_rows import (
    load_existing_bindings,
    load_existing_types,
    new_capability_binding,
    refresh_capability_binding,
    upsert_capability_type,
)
from .mcp_capability_policy import (
    MCP_CAPABILITY_REVIEW_STATE_NEEDS_REVIEW,
    mcp_capability_binding_key,
    normalized_mcp_server_name,
)


def _mirror_identity(workspace_id: str, server_name: str) -> tuple[str, str]:
    normalized_workspace_id = str(workspace_id or "").strip()
    # One canonical server identity for keys, config, and every later lookup.
    normalized_server = normalized_mcp_server_name(server_name)
    if not normalized_workspace_id or not normalized_server:
        raise ValueError("workspace_id and server_name are required to mirror MCP capabilities")
    server_error = server_identifier_error(normalized_server)
    if server_error is not None:
        raise ValueError(server_error)
    return normalized_workspace_id, normalized_server


def _mirrorable_tools(server_name: str, tools: Sequence[Any]) -> tuple[list[Any], list[str]]:
    discovered, rejected = discovered_mcp_tools(tools)
    # Identifiers that would not fit their persisted columns are rejected here,
    # before any write, instead of being truncated into a colliding key.
    oversized = [tool.name for tool in discovered if exceeds_mcp_identifier_limits(server_name, tool.name)]
    if oversized:
        rejected.extend(oversized)
        oversized_names = set(oversized)
        discovered = [tool for tool in discovered if tool.name not in oversized_names]
    return discovered, rejected


def _mirror_tools(
    db: AsyncSession,
    *,
    workspace_id: str,
    server_name: str,
    discovered: list[Any],
    mirrored_at: str,
    existing_types: dict[str, CapabilityType],
    existing_bindings: dict[str, WorkspaceCapabilityBinding],
) -> dict[str, Any]:
    """Create or refresh each tool's capability type and binding; the run's counters."""
    added = 0
    updated = 0
    drifted_tools: list[str] = []
    inactive_tools: list[str] = []
    for tool in discovered:
        binding_key = mcp_capability_binding_key(server_name, tool.name)
        contract = mcp_capability_contract(server_name=server_name, tool=tool)
        display_name = capability_display_name(server_name, tool.name)
        capability_type, retired = upsert_capability_type(
            db, existing_types, binding_key=binding_key, display_name=display_name, contract=contract
        )
        if retired:
            inactive_tools.append(tool.name)
        binding = existing_bindings.get(binding_key)
        if binding is None:
            db.add(
                new_capability_binding(
                    workspace_id=workspace_id, server_name=server_name, tool_name=tool.name,
                    binding_key=binding_key, capability_type=capability_type, display_name=display_name,
                    contract=contract, mirrored_at=mirrored_at,
                )
            )
            added += 1
            continue
        drifted, changed = refresh_capability_binding(
            binding, capability_type=capability_type, server_name=server_name, tool_name=tool.name,
            contract=contract, mirrored_at=mirrored_at,
        )
        if drifted:
            drifted_tools.append(tool.name)
        if changed:
            updated += 1
    return {"added": added, "updated": updated, "drifted": drifted_tools, "inactive": inactive_tools}


async def mirror_mcp_server_capabilities(
    db: AsyncSession,
    *,
    workspace_id: str,
    server_name: str,
    tools: Sequence[Any],
) -> dict[str, Any]:
    """Mirror one server's discovered tools into the workspace capability catalog."""
    normalized_workspace_id, normalized_server = _mirror_identity(workspace_id, server_name)
    discovered, rejected = _mirrorable_tools(normalized_server, tools)
    binding_keys = [mcp_capability_binding_key(normalized_server, tool.name) for tool in discovered]
    existing_types = await load_existing_types(db, binding_keys)
    existing_bindings = await load_existing_bindings(db, workspace_id=normalized_workspace_id, keys=binding_keys)

    mirrored_at = utc_now().isoformat()
    counts = _mirror_tools(
        db, workspace_id=normalized_workspace_id, server_name=normalized_server, discovered=discovered,
        mirrored_at=mirrored_at, existing_types=existing_types, existing_bindings=existing_bindings,
    )
    await db.flush()
    return {
        "server": normalized_server,
        "mirrored": len(discovered),
        "added": counts["added"],
        "updated": counts["updated"],
        "drifted": len(counts["drifted"]),
        "drifted_capabilities": sorted(counts["drifted"]),
        "rejected_capabilities": sorted(rejected),
        # Mirrored, contract refreshed, but still globally retired and therefore
        # still not dispatchable — reported instead of silently reactivated.
        "inactive_capabilities": sorted(counts["inactive"]),
    }


def acknowledged_mcp_capability_schema_config(binding_config: Any) -> dict[str, Any] | None:
    """Return the binding config with a pending schema review cleared, else ``None``.

    Enabling a mirrored capability *is* the review decision for the contract
    currently in the catalog. Pure on purpose: the admin write path composes this
    with its own sanitizing before the binding is written.
    """
    config = binding_config if isinstance(binding_config, dict) else {}
    if str(config.get("reviewState") or "").strip().lower() != MCP_CAPABILITY_REVIEW_STATE_NEEDS_REVIEW:
        return None
    cleared = {key: value for key, value in config.items() if key != "reviewState"}
    cleared["reviewAcknowledgedAt"] = utc_now().isoformat()
    cleared["acknowledgedSchemaDigest"] = str(config.get("schemaDigest") or "")
    return cleared


__all__ = [
    "acknowledged_mcp_capability_schema_config",
    "mirror_mcp_server_capabilities",
]
