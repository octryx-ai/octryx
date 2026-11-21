"""What an admin may change on a mirrored MCP capability binding.

``workspace_composition/admin_api.update_workspace_binding`` is the generic
binding editor: it writes ``binding_config`` and ``policy_config`` straight from
the request body. For ``capability_kind="mcp_capability"`` that is too much
reach, because those two mappings also carry the identity the mirror owns —
which server and tool the binding dispatches, the approved schema digest, the
drift review state. An admin who could write them freely could retarget a
binding onto another capability or clear a schema-drift review without
reviewing it.

The rule this module enforces:

- mirror-owned keys always come from the persisted row — a request that
  contradicts one is rejected, a request that omits one keeps the stored value;
- every other key in ``binding_config``/``policy_config`` is replaced by the
  request as is, and ``policy_config["risk"]`` must be one of the
  allow-listed risks instead of being silently coerced at decision time.

The one state transition an admin *can* trigger is the schema-drift review:
enabling a mirrored capability is the explicit decision to accept the contract
currently in the catalog, so the returned config has the review state cleared.

The admin-owned governance fields (``is_enabled``, ``is_default``,
``binding_status``, ``display_name``, ``intent_scopes``, and
``policy_config["risk"]``) are untouched here and keep their existing behavior.
Identity columns (``binding_key``, ``capability_type_id``, ``source_entity_*``)
are not part of the update payload at all, so they need no guard.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..models import WorkspaceCapabilityBinding
from .mcp_capability_catalog import acknowledged_mcp_capability_schema_config
from .mcp_capability_policy import MCP_CAPABILITY_RISKS

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
    """Return the payload an admin is allowed to apply to a mirrored MCP binding.

    Raises ``HTTPException`` when the request tries to take over mirror-owned
    identity or set a risk outside the allow-list.
    """
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
