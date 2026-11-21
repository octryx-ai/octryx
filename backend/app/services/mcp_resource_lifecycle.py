"""What happens to a mirrored MCP resource or prompt across mirror runs.

``mcp_resource_catalog`` writes what a server currently advertises. This module
owns the other half — what happens to catalog entries a run did *not* see, and
what happens when one of them comes back — plus the per-server mirror-history
marker, which is the same kind of run-to-run bookkeeping.

The rule is symmetric and fails closed in both directions:

- an item the server stopped advertising is retired to ``lifecycleState =
  "missing"`` and disabled. It stays in the catalog because its governance
  history (who enabled it, at what risk, under which scopes) is evidence an
  operator needs, but ``mcp_resource_policy`` refuses it, so it is neither
  discoverable nor executable;
- an item that reappears is **not** reactivated. Something on the far side
  changed while the platform could not see it, so the binding comes back
  disabled and parked in a contract review, exactly like real contract drift.
  Enabling it again is an explicit admin decision.

One thing is deliberately **not** absence: an item the run *saw* and *refused*.
A refusal — a credential in a provider-controlled metadata field, an identifier
the catalog cannot address — is a fact about what the server advertised, not
evidence that it stopped advertising it. Retiring an approved binding for it
would silently revoke an admin decision on the strength of one bad description,
so ``retire_missing_bindings`` keeps every refused key out of the missing
lifecycle and records the refusal distinctly (``mirrorRejection``) instead. The
prior lifecycle stands until a listing that actually answered proves the item is
gone.

Nothing here reads a raw URI: a retired, reappeared, or refused entry is reported
by its prompt name or its opaque resource identity digest, never by its URI.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CapabilityType, WorkspaceCapabilityBinding
from .mcp_capability_policy import normalized_mcp_server_name
from .mcp_resource_identity import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_MISSING,
    MCP_PROMPT_KIND,
    MCP_RESOURCE_MIRROR_SCOPE,
    MCP_RESOURCE_MIRROR_SOURCE_ENTITY_TYPE,
    MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW,
)


def _config(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def binding_item_label(binding: WorkspaceCapabilityBinding) -> str:
    """Return the credential-free label one binding is reported under."""
    config = _config(binding.binding_config)
    if str(binding.capability_kind or "").strip() == MCP_PROMPT_KIND:
        return str(config.get("promptName") or binding.binding_key or "")
    return str(config.get("resourceIdentity") or binding.binding_key or "")


async def load_mirrored_server_bindings(
    db: AsyncSession,
    *,
    workspace_id: str,
    kind: str,
    server_name: str,
) -> dict[str, WorkspaceCapabilityBinding]:
    """Return every binding of one kind this workspace holds for one server.

    Filtered on the persisted ``serverName`` rather than on a key prefix: a
    ``LIKE`` pattern would treat ``_`` and ``%`` in a server name as wildcards and
    could retire another server's catalog.
    """
    normalized_server = normalized_mcp_server_name(server_name)
    rows = (
        (
            await db.execute(
                select(WorkspaceCapabilityBinding).where(
                    WorkspaceCapabilityBinding.workspace_id == str(workspace_id or "").strip(),
                    WorkspaceCapabilityBinding.capability_kind == str(kind or "").strip(),
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        str(row.binding_key): row
        for row in rows
        if normalized_mcp_server_name(_config(row.binding_config).get("serverName")) == normalized_server
    }


def reappeared_binding_config(previous_config: Any, *, mirrored_at: str) -> dict[str, Any] | None:
    """Return the config of an item that came back, or ``None`` if it never left."""
    config = _config(previous_config)
    if str(config.get("lifecycleState") or LIFECYCLE_ACTIVE).strip().lower() != LIFECYCLE_MISSING:
        return None
    return {
        **config,
        "lifecycleState": LIFECYCLE_ACTIVE,
        "reappearedAt": mirrored_at,
        # A re-appearance is a review trigger, not a reactivation.
        "reviewState": MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW,
    }


def note_rejected_bindings(
    bindings: dict[str, WorkspaceCapabilityBinding],
    *,
    rejected_keys: dict[str, str],
    mirrored_at: str,
) -> list[str]:
    """Record that this run saw and refused these items, without retiring them.

    The binding keeps its lifecycle, its enablement, and its approved contract:
    the item still exists on the server, and only the refused *new* metadata was
    not mirrored. The marker is what makes the refusal visible to an operator
    instead of silent, and ``_write_item`` clears it on the first run that
    accepts the item again.
    """
    noted: list[str] = []
    for binding_key, reason in rejected_keys.items():
        binding = bindings.get(binding_key)
        if binding is None:
            continue
        config = _config(binding.binding_config)
        binding.binding_config = {
            **config,
            "mirrorRejection": {"reason": reason, "detectedAt": mirrored_at},
        }
        noted.append(binding_item_label(binding))
    return sorted(noted)


def retire_missing_bindings(
    bindings: dict[str, WorkspaceCapabilityBinding],
    *,
    present_keys: set[str],
    preserved_keys: set[str],
    marker_key: str,
    mirrored_at: str,
) -> list[str]:
    """Mark every catalog entry this run did not see as missing and disable it.

    ``preserved_keys`` are the entries the run *did* see and refused. They are
    not missing, so they are never retired here.
    """
    retired: list[str] = []
    for binding_key, binding in bindings.items():
        if binding_key in present_keys or binding_key in preserved_keys or binding_key == marker_key:
            continue
        config = _config(binding.binding_config)
        if not config.get("serverName"):
            continue
        retired.append(binding_item_label(binding))
        if str(config.get("lifecycleState") or LIFECYCLE_ACTIVE).strip().lower() == LIFECYCLE_MISSING:
            # Already retired; re-stamping the detection time would lose when the
            # item actually disappeared.
            continue
        binding.binding_config = {
            **config,
            "lifecycleState": LIFECYCLE_MISSING,
            "missingDetectedAt": mirrored_at,
        }
        binding.is_enabled = False
        binding.is_default = False
    return sorted(retired)


def record_mirror_history(
    db: AsyncSession,
    *,
    workspace_id: str,
    kind: str,
    server_name: str,
    marker_key: str,
    mirrored_at: str,
    entry_count: int,
    mirror_source: str,
    existing_types: dict[str, CapabilityType],
    existing_bindings: dict[str, WorkspaceCapabilityBinding],
) -> bool:
    """Persist that this workspace mirrored this kind for this server."""
    display_name = f"{server_name} ({kind} mirror)"
    marker_config = {
        "serverName": server_name,
        "mirrorScope": MCP_RESOURCE_MIRROR_SCOPE,
        "mirroredAt": mirrored_at,
        "entryCount": entry_count,
    }
    capability_type = existing_types.get(marker_key)
    if capability_type is None:
        capability_type = CapabilityType(
            id=str(uuid.uuid4()),
            kind=kind,
            key=marker_key,
            name=display_name,
            description=f"Mirror history marker for one MCP server's {kind} catalog.",
            lifecycle_status="active",
            contract={
                "sourceEntityType": MCP_RESOURCE_MIRROR_SOURCE_ENTITY_TYPE,
                "sourceEntityId": server_name,
                "serverName": server_name,
                "mirrorScope": MCP_RESOURCE_MIRROR_SCOPE,
            },
            is_active=True,
        )
        db.add(capability_type)
        existing_types[marker_key] = capability_type

    binding = existing_bindings.get(marker_key)
    if binding is not None:
        binding.binding_config = {**_config(binding.binding_config), **marker_config}
        return False
    db.add(
        WorkspaceCapabilityBinding(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            binding_key=marker_key,
            capability_type=capability_type,
            capability_kind=kind,
            display_name=display_name,
            # Never enabled and never visible: governance history, not an item.
            binding_status="hidden",
            is_enabled=False,
            is_default=False,
            intent_scopes=[],
            source_entity_type=MCP_RESOURCE_MIRROR_SOURCE_ENTITY_TYPE,
            source_entity_id=server_name,
            binding_config=marker_config,
            policy_config={"source": mirror_source, "mirrorScope": MCP_RESOURCE_MIRROR_SCOPE},
        )
    )
    return True


__all__ = [
    "binding_item_label",
    "load_mirrored_server_bindings",
    "note_rejected_bindings",
    "reappeared_binding_config",
    "record_mirror_history",
    "retire_missing_bindings",
]
