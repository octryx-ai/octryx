"""What an admin may change on a mirrored MCP resource or prompt binding.

``workspace_composition/admin_api.update_workspace_binding`` is the generic
binding editor: it writes ``binding_config`` and ``policy_config`` straight from
the request body. For the governed resource/prompt kinds that is too much reach,
because those two mappings also carry the identity the mirror owns — which server
and item the binding addresses, the governed URI, the approved contract digest,
the drift review state, and the per-server mirror-history marker. An admin who
could write them freely could retarget a binding onto another resource, point an
enabled binding at a different URI, clear a contract-drift review without
reviewing it, or delete the marker discovery reports on.

This is the sibling of ``mcp_capability_admin_policy`` for the ``mcp_resource``
and ``mcp_prompt`` kinds, and it enforces the same rule:

- a mirror-history marker binding is server-owned and not editable at all;
- mirror-owned keys always come from the persisted row — a request that
  contradicts one is rejected, a request that omits one keeps the stored value;
- every other key is replaced by the request as is, and
  ``policy_config["risk"]`` must be allow-listed instead of being silently coerced
  at decision time.

The one state transition an admin *can* trigger is the contract-drift review:
enabling a mirrored item is the explicit decision to accept the contract currently
in the catalog, so the returned config has the review state cleared and its
approved digest re-pinned to the catalog's own. The upstream lifecycle is not such
a transition — an item the server stopped advertising stays ``missing`` and stays
non-executable no matter what an admin enables, until the mirror sees it again.

The admin-owned governance fields (``is_enabled``, ``is_default``,
``binding_status``, ``display_name``, ``intent_scopes``, and
``policy_config["risk"]``) are untouched here and keep their existing behavior.
Identity columns are not part of the update payload at all, so they need no guard.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..models import WorkspaceCapabilityBinding
from .mcp_resource_catalog import acknowledged_mcp_resource_contract_config
from .mcp_resource_identity import MCP_RESOURCE_RISKS
from .mcp_resource_index import is_mcp_resource_mirror_marker

# Written by ``mcp_resource_catalog``; the catalog is their only author.
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
    """Return the payload an admin may apply to a mirrored resource/prompt binding.

    Raises ``HTTPException`` when the request tries to take over mirror-owned
    identity, edit a mirror-history marker, or set a risk outside the allow-list.
    """
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
