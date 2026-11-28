"""The per-item writes of one MCP resource mirror run."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CapabilityType, WorkspaceCapabilityBinding
from .resource_catalog_items import MCP_RESOURCE_MIRROR_SOURCE, _MirrorItem, _MirrorTally
from .resource_identity import (
    DEFAULT_MCP_RESOURCE_RISK,
    LIFECYCLE_ACTIVE,
    MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW,
)
from .resource_lifecycle import reappeared_binding_config
from .resource_types import MirroredBindingConfig


def _upsert_capability_type(
    db: AsyncSession,
    item: _MirrorItem,
    *,
    existing_types: dict[str, CapabilityType],
    tally: _MirrorTally,
) -> CapabilityType:
    capability_type = existing_types.get(item.binding_key)
    if capability_type is None:
        capability_type = CapabilityType(
            id=str(uuid.uuid4()),
            kind=item.kind,
            key=item.binding_key,
            name=item.display_name,
            description=item.contract.get("description") or "",
            lifecycle_status="active",
            contract=item.contract,
            is_active=True,
        )
        db.add(capability_type)
        existing_types[item.binding_key] = capability_type
    else:
        # Contract refresh only. ``is_active`` is catalog lifecycle state an admin
        # owns: a retired item must stay retired, so a re-mirror can never
        # silently reactivate it and widen the governed surface.
        capability_type.name = item.display_name
        capability_type.description = item.contract.get("description") or ""
        capability_type.contract = item.contract
        if not capability_type.is_active:
            tally.inactive.append(item.label)
    return capability_type


def _new_binding(
    item: _MirrorItem,
    *,
    capability_type: CapabilityType,
    workspace_id: str,
    server_name: str,
    mirrored_at: str,
    digest: str,
) -> WorkspaceCapabilityBinding:
    return WorkspaceCapabilityBinding(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        binding_key=item.binding_key,
        capability_type=capability_type,
        capability_kind=item.kind,
        display_name=item.display_name,
        binding_status="active",
        is_enabled=False,
        is_default=False,
        intent_scopes=[],
        source_entity_type=item.source_entity_type,
        source_entity_id=item.source_entity_id,
        binding_config={
            "serverName": server_name,
            **item.identity_config,
            "contractDigest": digest,
            "mirroredAt": mirrored_at,
            "lifecycleState": LIFECYCLE_ACTIVE,
        },
        # Risk stays explicit metadata an admin owns; it is never inferred
        # from a URI, a name, or a description.
        policy_config={"risk": DEFAULT_MCP_RESOURCE_RISK, "source": MCP_RESOURCE_MIRROR_SOURCE},
    )


def _refreshed_config(
    previous_config: dict[str, Any],
    item: _MirrorItem,
    *,
    server_name: str,
    mirrored_at: str,
    digest: str,
    previous_digest: str,
    has_drift: bool,
) -> MirroredBindingConfig:
    return {
        **previous_config,
        "serverName": server_name,
        **item.identity_config,
        "contractDigest": digest,
        "mirroredAt": mirrored_at,
        **(
            {
                "previousContractDigest": previous_digest,
                "driftDetectedAt": mirrored_at,
                # Persisted deny state: the contract an admin approved no longer
                # exists, so the item needs an explicit review.
                "reviewState": MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW,
            }
            if has_drift
            else {}
        ),
    }


def _refresh_binding(
    binding: WorkspaceCapabilityBinding,
    item: _MirrorItem,
    *,
    capability_type: CapabilityType,
    server_name: str,
    mirrored_at: str,
    digest: str,
    tally: _MirrorTally,
) -> None:
    previous_config = binding.binding_config if isinstance(binding.binding_config, dict) else {}
    # A run that accepts the item again clears the refusal marker a previous run
    # left, so ``mirrorRejection`` always describes the latest run's answer.
    cleared_rejection = "mirrorRejection" in previous_config
    if cleared_rejection:
        previous_config = {key: value for key, value in previous_config.items() if key != "mirrorRejection"}
    reappeared = reappeared_binding_config(previous_config, mirrored_at=mirrored_at)
    if reappeared is not None:
        # The item is back, but something changed while it was gone: it returns
        # disabled and parked for review rather than silently reactivated.
        previous_config = reappeared
        tally.reappeared.append(item.label)
    previous_digest = str(previous_config.get("contractDigest") or "")
    has_drift = bool(previous_digest) and previous_digest != digest
    if has_drift:
        tally.drifted.append(item.label)
    if (
        reappeared is None
        and not cleared_rejection
        and previous_digest == digest
        and previous_config.get("serverName") == server_name
    ):
        return
    binding.capability_type = capability_type
    binding.display_name = item.display_name
    binding.binding_config = _refreshed_config(
        previous_config,
        item,
        server_name=server_name,
        mirrored_at=mirrored_at,
        digest=digest,
        previous_digest=previous_digest,
        has_drift=has_drift,
    )
    if has_drift or reappeared is not None:
        binding.is_enabled = False
        binding.is_default = False
    tally.updated += 1


def _write_item(
    db: AsyncSession,
    item: _MirrorItem,
    *,
    workspace_id: str,
    server_name: str,
    mirrored_at: str,
    existing_types: dict[str, CapabilityType],
    existing_bindings: dict[str, WorkspaceCapabilityBinding],
    tally: _MirrorTally,
) -> None:
    capability_type = _upsert_capability_type(db, item, existing_types=existing_types, tally=tally)
    digest = str(item.contract.get("contractDigest") or "")
    binding = existing_bindings.get(item.binding_key)
    if binding is None:
        db.add(
            _new_binding(
                item,
                capability_type=capability_type,
                workspace_id=workspace_id,
                server_name=server_name,
                mirrored_at=mirrored_at,
                digest=digest,
            )
        )
        tally.added += 1
        return
    _refresh_binding(
        binding,
        item,
        capability_type=capability_type,
        server_name=server_name,
        mirrored_at=mirrored_at,
        digest=digest,
        tally=tally,
    )
