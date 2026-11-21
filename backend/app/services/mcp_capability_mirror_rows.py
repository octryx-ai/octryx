"""The catalog rows one MCP capability mirror run reads and writes.

:mod:`.mcp_capability_catalog` drives the run; this module builds and refreshes
the individual ``CapabilityType`` and ``WorkspaceCapabilityBinding`` rows. A new
binding is always disabled, and a refresh
never rewrites admin-owned governance state except to park a drifted contract
for review.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CapabilityType, WorkspaceCapabilityBinding
from .mcp_capability_contract import capability_source_entity_id
from .mcp_capability_policy import (
    DEFAULT_MCP_CAPABILITY_RISK,
    MCP_CAPABILITY_KIND,
    MCP_CAPABILITY_REVIEW_STATE_NEEDS_REVIEW,
    MCP_CAPABILITY_SOURCE_ENTITY_TYPE,
)

MCP_CAPABILITY_MIRROR_SOURCE = "mcp_capability_mirror"


async def load_existing_types(db: AsyncSession, keys: list[str]) -> dict[str, CapabilityType]:
    if not keys:
        return {}
    rows = (
        (
            await db.execute(
                select(CapabilityType).where(
                    CapabilityType.kind == MCP_CAPABILITY_KIND,
                    CapabilityType.key.in_(keys),
                )
            )
        )
        .scalars()
        .all()
    )
    return {str(row.key): row for row in rows}


async def load_existing_bindings(
    db: AsyncSession,
    *,
    workspace_id: str,
    keys: list[str],
) -> dict[str, WorkspaceCapabilityBinding]:
    if not keys:
        return {}
    rows = (
        (
            await db.execute(
                select(WorkspaceCapabilityBinding).where(
                    WorkspaceCapabilityBinding.workspace_id == workspace_id,
                    WorkspaceCapabilityBinding.binding_key.in_(keys),
                )
            )
        )
        .scalars()
        .all()
    )
    return {str(row.binding_key): row for row in rows}


def upsert_capability_type(
    db: AsyncSession,
    existing_types: dict[str, CapabilityType],
    *,
    binding_key: str,
    display_name: str,
    contract: dict[str, Any],
) -> tuple[CapabilityType, bool]:
    """The capability type for one tool, created or contract-refreshed; whether it stays globally retired."""
    capability_type = existing_types.get(binding_key)
    if capability_type is None:
        capability_type = CapabilityType(
            id=str(uuid.uuid4()),
            kind=MCP_CAPABILITY_KIND,
            key=binding_key,
            name=display_name,
            description=contract["description"],
            lifecycle_status="active",
            contract=contract,
            is_active=True,
        )
        db.add(capability_type)
        existing_types[binding_key] = capability_type
        return capability_type, False
    # Contract refresh only. ``is_active`` is catalog lifecycle state an
    # admin owns: a globally retired capability must stay retired, so a
    # re-mirror can never silently reactivate it and widen execution.
    capability_type.name = display_name
    capability_type.description = contract["description"]
    capability_type.contract = contract
    return capability_type, not capability_type.is_active


def new_capability_binding(
    *,
    workspace_id: str,
    server_name: str,
    tool_name: str,
    binding_key: str,
    capability_type: CapabilityType,
    display_name: str,
    contract: dict[str, Any],
    mirrored_at: str,
) -> WorkspaceCapabilityBinding:
    """A disabled binding for a newly mirrored tool; an admin enables it."""
    return WorkspaceCapabilityBinding(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        binding_key=binding_key,
        capability_type=capability_type,
        capability_kind=MCP_CAPABILITY_KIND,
        display_name=display_name,
        binding_status="active",
        is_enabled=False,
        is_default=False,
        intent_scopes=[],
        source_entity_type=MCP_CAPABILITY_SOURCE_ENTITY_TYPE,
        source_entity_id=capability_source_entity_id(server_name, tool_name),
        binding_config={
            "serverName": server_name,
            "toolName": tool_name,
            "schemaDigest": contract["schemaDigest"],
            "mirroredAt": mirrored_at,
        },
        # Risk stays explicit metadata an admin owns; it is never
        # inferred from the capability name or description.
        policy_config={"risk": DEFAULT_MCP_CAPABILITY_RISK, "source": MCP_CAPABILITY_MIRROR_SOURCE},
    )


def refresh_capability_binding(
    binding: WorkspaceCapabilityBinding,
    *,
    capability_type: CapabilityType,
    server_name: str,
    tool_name: str,
    contract: dict[str, Any],
    mirrored_at: str,
) -> tuple[bool, bool]:
    """Refresh an existing binding's contract digest; ``(drifted, updated)``."""
    previous_config = binding.binding_config if isinstance(binding.binding_config, dict) else {}
    previous_digest = str(previous_config.get("schemaDigest") or "")
    has_drift = bool(previous_digest) and previous_digest != contract["schemaDigest"]
    if previous_digest == contract["schemaDigest"] and previous_config.get("serverName") == server_name:
        return has_drift, False
    binding.capability_type = capability_type
    binding.binding_config = {
        **previous_config,
        "serverName": server_name,
        "toolName": tool_name,
        "schemaDigest": contract["schemaDigest"],
        "mirroredAt": mirrored_at,
        **(
            {
                "previousSchemaDigest": previous_digest,
                "driftDetectedAt": mirrored_at,
                # Persisted deny state: the contract an admin approved no
                # longer exists, so the capability needs an explicit review
                # instead of a counter that vanishes with this response.
                "reviewState": MCP_CAPABILITY_REVIEW_STATE_NEEDS_REVIEW,
            }
            if has_drift
            else {}
        ),
    }
    if has_drift:
        binding.is_enabled = False
        binding.is_default = False
    return has_drift, True


__all__ = [
    "MCP_CAPABILITY_MIRROR_SOURCE",
    "load_existing_bindings",
    "load_existing_types",
    "new_capability_binding",
    "refresh_capability_binding",
    "upsert_capability_type",
]
