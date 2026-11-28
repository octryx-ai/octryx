"""What one MCP resource mirror run writes per discovered item, and the per-kind tally it reports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .resource_contract import (
    RejectedMcpMirrorEntry,
    mcp_prompt_contract,
    mcp_resource_contract,
    prompt_display_name,
    prompt_source_entity_id,
    resource_display_name,
)
from .resource_contract_discovery import discovered_mcp_prompts, discovered_mcp_resources
from .resource_identity import (
    MCP_PROMPT_KIND,
    MCP_PROMPT_SOURCE_ENTITY_TYPE,
    MCP_RESOURCE_KIND,
    MCP_RESOURCE_SOURCE_ENTITY_TYPE,
    mcp_prompt_binding_key,
    mcp_resource_binding_key,
)

MCP_RESOURCE_MIRROR_SOURCE = "mcp_resource_mirror"


@dataclass(frozen=True, slots=True)
class _MirrorItem:
    kind: str
    binding_key: str
    display_name: str
    source_entity_type: str
    source_entity_id: str
    contract: dict[str, Any]
    identity_config: dict[str, Any]
    # How this item is named back to an admin: the opaque identity for a
    # resource, the prompt name for a prompt. Never a URI.
    label: str


@dataclass(slots=True)
class _MirrorTally:
    added: int = 0
    updated: int = 0
    drifted: list[str] = field(default_factory=list)
    inactive: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reappeared: list[str] = field(default_factory=list)
    mirrored: int = 0
    history_recorded: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "mirrored": self.mirrored,
            "added": self.added,
            "updated": self.updated,
            "drifted": len(self.drifted),
            "drifted_entries": sorted(self.drifted),
            "rejected_entries": sorted(self.rejected),
            # Bindings this run refused but deliberately did not retire: the item
            # is still advertised, so its governance state stands.
            "preserved_entries": sorted(self.preserved),
            "inactive_entries": sorted(self.inactive),
            "missing_entries": sorted(self.missing),
            "reappeared_entries": sorted(self.reappeared),
            "mirror_history_recorded": self.history_recorded,
        }


def _resource_items(
    server_name: str, resources: Sequence[Any]
) -> tuple[list[_MirrorItem], list[RejectedMcpMirrorEntry]]:
    discovered, rejected = discovered_mcp_resources(server_name, resources)
    items = []
    for resource in discovered:
        contract = mcp_resource_contract(server_name=server_name, resource=resource)
        items.append(
            _MirrorItem(
                kind=MCP_RESOURCE_KIND,
                binding_key=mcp_resource_binding_key(server_name, resource.identity),
                display_name=resource_display_name(server_name, resource.governed_uri),
                source_entity_type=MCP_RESOURCE_SOURCE_ENTITY_TYPE,
                source_entity_id=resource.identity,
                contract=contract,
                identity_config={
                    "resourceIdentity": resource.identity,
                    "resourceUri": resource.governed_uri,
                },
                # Reported by the opaque identity, the same one discovery
                # publishes, so no mirror payload ever echoes a resource URI.
                label=resource.identity,
            )
        )
    return items, rejected


def _prompt_items(
    server_name: str, prompts: Sequence[Any]
) -> tuple[list[_MirrorItem], list[RejectedMcpMirrorEntry]]:
    discovered, rejected = discovered_mcp_prompts(server_name, prompts)
    items = []
    for prompt in discovered:
        contract = mcp_prompt_contract(server_name=server_name, prompt=prompt)
        items.append(
            _MirrorItem(
                kind=MCP_PROMPT_KIND,
                binding_key=mcp_prompt_binding_key(server_name, prompt.name),
                display_name=prompt_display_name(server_name, prompt.name),
                source_entity_type=MCP_PROMPT_SOURCE_ENTITY_TYPE,
                source_entity_id=prompt_source_entity_id(server_name, prompt.name),
                contract=contract,
                identity_config={"promptName": prompt.name},
                label=prompt.name,
            )
        )
    return items, rejected


__all__ = ["MCP_RESOURCE_MIRROR_SOURCE"]
