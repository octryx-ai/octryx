"""What an admin may change on a mirrored MCP capability binding: mirror-owned keys stay, the risk is
allow-listed."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...models import WorkspaceCapabilityBinding
from ..mcp_capability_catalog import acknowledged_mcp_capability_schema_config
from .capability_policy import MCP_CAPABILITY_RISKS

# Written by ``mcp_capability_catalog``; the catalog is their only author.
MIRROR_OWNED_BINDING_CONFIG_KEYS = frozenset(
    {
        "serverName",
        "toolName",
        "mirrorScope",
        "schemaDigest",
        "previousSchemaDigest",
        "driftDetectedAt",
        "mirroredAt",
        "reviewState",
        "reviewAcknowledgedAt",
        "acknowledgedSchemaDigest",
        "capabilityCount",
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
                    f"MCP capability {field_name} field '{key}' is owned by the capability mirror "
                    "and cannot be changed through a binding update"
                ),
            )
    # Mirror-owned keys always come from the persisted row; every other key is
    # replaced by the request exactly as the generic binding editor does it, so
    # admin-owned entries stay editable and removable.
    merged = {key: value for key, value in current.items() if key in owned_keys}
    merged.update({key: value for key, value in requested.items() if key not in owned_keys})
    return merged


def _validated_risk(value: Any) -> str:
    risk = str(value or "").strip().lower()
    if risk not in MCP_CAPABILITY_RISKS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported MCP capability risk; use one of: {', '.join(sorted(MCP_CAPABILITY_RISKS))}",
        )
    return risk


def guard_mcp_capability_binding_update(
    binding: WorkspaceCapabilityBinding,
    payload: dict[str, Any],
) -> dict[str, Any]:
    # Mirror-owned identity and a risk outside the allow-list are refused.
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
        # Enabling is the review decision for the contract currently mirrored.
        binding_config = acknowledged_mcp_capability_schema_config(binding_config) or binding_config
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
    "guard_mcp_capability_binding_update",
]
