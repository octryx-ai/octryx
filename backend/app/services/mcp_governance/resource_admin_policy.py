"""What an admin may change on a mirrored MCP resource or prompt binding: mirror-owned keys and markers stay,
the risk is allow-listed."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...models import WorkspaceCapabilityBinding
from .resource_catalog import acknowledged_mcp_resource_contract_config
from .resource_identity import MCP_RESOURCE_RISKS
from .resource_index import is_mcp_resource_mirror_marker

# Written by ``mcp_governance.resource_catalog``; the catalog is their only author.
MIRROR_OWNED_BINDING_CONFIG_KEYS = frozenset(
    {
        "serverName",
        "mirrorScope",
        "resourceIdentity",
        "resourceUri",
        "promptName",
        "contractDigest",
        "previousContractDigest",
        "driftDetectedAt",
        "mirroredAt",
        "lifecycleState",
        "missingDetectedAt",
        "reappearedAt",
        "reviewState",
        "reviewAcknowledgedAt",
        "acknowledgedContractDigest",
        "entryCount",
    }
)
MIRROR_OWNED_POLICY_CONFIG_KEYS = frozenset({"source", "mirrorScope"})


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _merge_server_owned(
    *,
    requested: dict[str, Any],
    current: dict[str, Any],
    owned_keys: frozenset[str],
    field_name: str,
) -> dict[str, Any]:
    for key in sorted(owned_keys):
        if key in requested and requested[key] != current.get(key):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"MCP resource {field_name} field '{key}' is owned by the resource mirror "
                    "and cannot be changed through a binding update"
                ),
            )
    merged = {key: value for key, value in current.items() if key in owned_keys}
    merged.update({key: value for key, value in requested.items() if key not in owned_keys})
    return merged


def _validated_risk(value: Any) -> str:
    risk = str(value or "").strip().lower()
    if risk not in MCP_RESOURCE_RISKS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported MCP resource risk; use one of: {', '.join(sorted(MCP_RESOURCE_RISKS))}",
        )
    return risk


def guard_mcp_resource_binding_update(
    binding: WorkspaceCapabilityBinding,
    payload: dict[str, Any],
) -> dict[str, Any]:
    # Mirror-owned identity, mirror-history markers and a risk outside the allow-list are refused.
    if is_mcp_resource_mirror_marker(binding):
        raise HTTPException(
            status_code=400,
            detail="MCP mirror-history markers are server-owned governance records and cannot be edited",
        )
    guarded = dict(payload)

    binding_config = _mapping(binding.binding_config)
    if payload.get("binding_config") is not None:
        binding_config = _merge_server_owned(
            requested=_mapping(payload.get("binding_config")),
            current=binding_config,
            owned_keys=MIRROR_OWNED_BINDING_CONFIG_KEYS,
            field_name="binding_config",
        )
    if payload.get("is_enabled") is True:
        # Enabling is the review decision for the contract currently mirrored, so
        # the approved digest moves to the one the shared catalog now holds.
        catalog_contract = getattr(binding.capability_type, "contract", None)
        binding_config = (
            acknowledged_mcp_resource_contract_config(
                binding_config,
                catalog_contract_digest=str(_mapping(catalog_contract).get("contractDigest") or ""),
            )
            or binding_config
        )
    guarded["binding_config"] = binding_config

    if payload.get("policy_config") is not None:
        requested_policy = _mapping(payload.get("policy_config"))
        if "risk" in requested_policy:
            requested_policy["risk"] = _validated_risk(requested_policy.get("risk"))
        guarded["policy_config"] = _merge_server_owned(
            requested=requested_policy,
            current=_mapping(binding.policy_config),
            owned_keys=MIRROR_OWNED_POLICY_CONFIG_KEYS,
            field_name="policy_config",
        )

    return guarded


__all__ = [
    "MIRROR_OWNED_BINDING_CONFIG_KEYS",
    "MIRROR_OWNED_POLICY_CONFIG_KEYS",
    "guard_mcp_resource_binding_update",
]
