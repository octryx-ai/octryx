"""Mirror discovered MCP resources and prompts into the Workspace catalog as disabled bindings."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CapabilityType, WorkspaceCapabilityBinding
from ...time_utils import utc_now
from .capability_policy import normalized_mcp_server_name
from .resource_catalog_items import (
    MCP_RESOURCE_MIRROR_SOURCE,
    _MirrorItem,
    _MirrorTally,
    _prompt_items,
    _resource_items,
)
from .resource_catalog_write import _write_item
from .resource_contract import RejectedMcpMirrorEntry, mcp_resource_server_error
from .resource_identity import (
    MCP_PROMPT_KIND,
    MCP_RESOURCE_KIND,
    MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW,
    mcp_resource_server_marker_key,
)
from .resource_lifecycle import (
    load_mirrored_server_bindings,
    note_rejected_bindings,
    record_mirror_history,
    retire_missing_bindings,
)


async def _load_existing(
    db: AsyncSession,
    *,
    workspace_id: str,
    kind: str,
    server_name: str,
    keys: list[str],
) -> tuple[dict[str, CapabilityType], dict[str, WorkspaceCapabilityBinding]]:
    # Every binding, not only ``keys``: retiring what the server no longer advertises is the other half of mirroring.
    types = (
        (
            await db.execute(
                select(CapabilityType).where(CapabilityType.kind == kind, CapabilityType.key.in_(keys or [""]))
            )
        )
        .scalars()
        .all()
    )
    bindings = await load_mirrored_server_bindings(db, workspace_id=workspace_id, kind=kind, server_name=server_name)
    return {str(row.key): row for row in types}, bindings


async def _mirror_kind(
    db: AsyncSession,
    *,
    workspace_id: str,
    server_name: str,
    kind: str,
    items: list[_MirrorItem],
    rejected: list[RejectedMcpMirrorEntry],
    mirrored_at: str,
) -> dict[str, Any]:
    tally = _MirrorTally(mirrored=len(items), rejected=[entry.label for entry in rejected])
    marker_key = mcp_resource_server_marker_key(kind, server_name)
    existing_types, existing_bindings = await _load_existing(
        db,
        workspace_id=workspace_id,
        kind=kind,
        server_name=server_name,
        keys=[*(item.binding_key for item in items), marker_key],
    )
    for item in items:
        _write_item(
            db,
            item,
            workspace_id=workspace_id,
            server_name=server_name,
            mirrored_at=mirrored_at,
            existing_types=existing_types,
            existing_bindings=existing_bindings,
            tally=tally,
        )
    # Seen and refused is not absent. These keys keep their lifecycle and only
    # gain a refusal marker, so a single credential-bearing description cannot
    # retire a binding an admin approved.
    rejected_keys = {entry.binding_key: entry.reason for entry in rejected if entry.binding_key}
    tally.preserved = note_rejected_bindings(
        existing_bindings,
        rejected_keys=rejected_keys,
        mirrored_at=mirrored_at,
    )
    tally.missing = retire_missing_bindings(
        existing_bindings,
        present_keys={item.binding_key for item in items},
        preserved_keys=set(rejected_keys),
        marker_key=marker_key,
        mirrored_at=mirrored_at,
    )
    tally.history_recorded = record_mirror_history(
        db,
        workspace_id=workspace_id,
        kind=kind,
        server_name=server_name,
        marker_key=marker_key,
        mirrored_at=mirrored_at,
        entry_count=len(items),
        mirror_source=MCP_RESOURCE_MIRROR_SOURCE,
        existing_types=existing_types,
        existing_bindings=existing_bindings,
    )
    return tally.as_payload()


# Every entry this run did not see is marked missing and disabled, so the caller passes a complete listing.
async def mirror_mcp_server_resources(
    db: AsyncSession,
    *,
    workspace_id: str,
    server_name: str,
    resources: Sequence[Any],
    prompts: Sequence[Any],
) -> dict[str, Any]:
    normalized_workspace_id = str(workspace_id or "").strip()
    normalized_server = normalized_mcp_server_name(server_name)
    if not normalized_workspace_id or not normalized_server:
        raise ValueError("workspace_id and server_name are required to mirror MCP resources")
    server_error = mcp_resource_server_error(normalized_server)
    if server_error is not None:
        raise ValueError(server_error)

    mirrored_at = utc_now().isoformat()
    resource_items, rejected_resources = _resource_items(normalized_server, resources)
    prompt_items, rejected_prompts = _prompt_items(normalized_server, prompts)
    resource_result = await _mirror_kind(
        db,
        workspace_id=normalized_workspace_id,
        server_name=normalized_server,
        kind=MCP_RESOURCE_KIND,
        items=resource_items,
        rejected=rejected_resources,
        mirrored_at=mirrored_at,
    )
    prompt_result = await _mirror_kind(
        db,
        workspace_id=normalized_workspace_id,
        server_name=normalized_server,
        kind=MCP_PROMPT_KIND,
        items=prompt_items,
        rejected=rejected_prompts,
        mirrored_at=mirrored_at,
    )
    await db.flush()
    return {"server": normalized_server, "resources": resource_result, "prompts": prompt_result}


def acknowledged_mcp_resource_contract_config(
    binding_config: Any,
    *,
    catalog_contract_digest: str = "",
) -> dict[str, Any] | None:
    # Re-pins the approved digest to the catalog's own: another workspace's mirror run moves the shared contract, and
    # every bound workspace denies until it accepts.
    config = binding_config if isinstance(binding_config, dict) else {}
    approved_digest = str(config.get("contractDigest") or "").strip()
    catalog_digest = str(catalog_contract_digest or "").strip()
    pending_review = str(config.get("reviewState") or "").strip().lower() == MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW
    if not pending_review and approved_digest == catalog_digest:
        return None
    cleared = {key: value for key, value in config.items() if key != "reviewState"}
    cleared["contractDigest"] = catalog_digest or approved_digest
    cleared["reviewAcknowledgedAt"] = utc_now().isoformat()
    cleared["acknowledgedContractDigest"] = cleared["contractDigest"]
    return cleared


__all__ = [
    "acknowledged_mcp_resource_contract_config",
    "mirror_mcp_server_resources",
]
