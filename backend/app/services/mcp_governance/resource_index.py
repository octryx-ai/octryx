"""One Workspace's mirrored MCP resource and prompt catalog, as the item policy reads it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import WorkspaceCapabilityBinding
from .capability_policy import normalized_mcp_server_name
from .resource_identity import (
    LIFECYCLE_ACTIVE,
    MCP_PROMPT_KIND,
    MCP_RESOURCE_BINDING_KINDS,
    MCP_RESOURCE_MIRROR_SCOPE,
    normalized_mcp_resource_risk,
)


@dataclass(frozen=True, slots=True)
class MirroredMcpResourceEntry:
    kind: str
    server_name: str
    identity: str
    governed_identity: str
    binding_key: str
    binding_status: str
    is_enabled: bool
    capability_type_active: bool
    risk: str
    scopes: tuple[str, ...]
    review_state: str
    # The contract digest the workspace approved, next to the one the shared
    # ``CapabilityType`` currently carries. ``CapabilityType`` is global, so a
    # mirror run in one workspace rewrites it for every workspace bound to it;
    # comparing the two is what makes drift fail closed per workspace.
    approved_contract_digest: str = ""
    catalog_contract_digest: str = ""
    lifecycle_state: str = LIFECYCLE_ACTIVE
    contract: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class McpResourceIndex:
    workspace_id: str
    entries: Mapping[tuple[str, str, str], MirroredMcpResourceEntry] = field(default_factory=dict)
    mirrored_servers: frozenset[tuple[str, str]] = frozenset()

    def get(self, kind: str, server_name: str, identity: str) -> MirroredMcpResourceEntry | None:
        key = (str(kind or "").strip(), normalized_mcp_server_name(server_name), str(identity or "").strip())
        return self.entries.get(key)

    def has_mirror_history(self, kind: str, server_name: str) -> bool:
        return (str(kind or "").strip(), normalized_mcp_server_name(server_name)) in self.mirrored_servers

    def entries_for(self, kind: str, server_name: str) -> list[MirroredMcpResourceEntry]:
        normalized_kind = str(kind or "").strip()
        normalized_server = normalized_mcp_server_name(server_name)
        return [
            entry
            for (entry_kind, entry_server, _), entry in self.entries.items()
            if entry_kind == normalized_kind and entry_server == normalized_server
        ]


def is_mcp_resource_mirror_marker(binding: WorkspaceCapabilityBinding) -> bool:
    binding_config = binding.binding_config if isinstance(binding.binding_config, dict) else {}
    return str(binding_config.get("mirrorScope") or "").strip().lower() == MCP_RESOURCE_MIRROR_SCOPE


def _binding_entry(
    binding: WorkspaceCapabilityBinding,
    *,
    kind: str,
    server_name: str,
) -> MirroredMcpResourceEntry | None:
    binding_config = binding.binding_config if isinstance(binding.binding_config, dict) else {}
    policy_config = binding.policy_config if isinstance(binding.policy_config, dict) else {}
    if kind == MCP_PROMPT_KIND:
        identity = str(binding_config.get("promptName") or "").strip()
        governed_identity = identity
    else:
        identity = str(binding_config.get("resourceIdentity") or "").strip()
        governed_identity = str(binding_config.get("resourceUri") or "").strip()
    if not identity or not governed_identity:
        return None
    contract = getattr(binding.capability_type, "contract", None)
    contract_mapping = contract if isinstance(contract, dict) else {}
    return MirroredMcpResourceEntry(
        kind=kind,
        server_name=server_name,
        identity=identity,
        governed_identity=governed_identity,
        binding_key=str(binding.binding_key or ""),
        binding_status=str(binding.binding_status or "").strip().lower(),
        is_enabled=bool(binding.is_enabled),
        capability_type_active=bool(getattr(binding.capability_type, "is_active", False)),
        risk=normalized_mcp_resource_risk(policy_config.get("risk")),
        scopes=tuple(str(scope).strip() for scope in (binding.intent_scopes or []) if str(scope).strip()),
        review_state=str(binding_config.get("reviewState") or "").strip().lower(),
        approved_contract_digest=str(binding_config.get("contractDigest") or "").strip(),
        catalog_contract_digest=str(contract_mapping.get("contractDigest") or "").strip(),
        lifecycle_state=str(binding_config.get("lifecycleState") or LIFECYCLE_ACTIVE).strip().lower(),
        contract=contract_mapping,
    )


async def load_mcp_resource_index(db: AsyncSession, *, workspace_id: str) -> McpResourceIndex:
    normalized_workspace_id = str(workspace_id or "").strip()
    if not normalized_workspace_id:
        return McpResourceIndex(workspace_id="")
    rows = (
        (
            await db.execute(
                select(WorkspaceCapabilityBinding)
                .options(selectinload(WorkspaceCapabilityBinding.capability_type))
                .where(
                    WorkspaceCapabilityBinding.workspace_id == normalized_workspace_id,
                    WorkspaceCapabilityBinding.capability_kind.in_(sorted(MCP_RESOURCE_BINDING_KINDS)),
                )
            )
        )
        .scalars()
        .all()
    )
    entries: dict[tuple[str, str, str], MirroredMcpResourceEntry] = {}
    mirrored_servers: set[tuple[str, str]] = set()
    for row in rows:
        kind = str(row.capability_kind or "").strip()
        binding_config = row.binding_config if isinstance(row.binding_config, dict) else {}
        server_name = normalized_mcp_server_name(binding_config.get("serverName"))
        if not server_name or kind not in MCP_RESOURCE_BINDING_KINDS:
            continue
        if is_mcp_resource_mirror_marker(row):
            # History only: a marker carries no identity and can never resolve.
            mirrored_servers.add((kind, server_name))
            continue
        entry = _binding_entry(row, kind=kind, server_name=server_name)
        if entry is not None:
            entries[(kind, server_name, entry.identity)] = entry
            mirrored_servers.add((kind, server_name))
    return McpResourceIndex(
        workspace_id=normalized_workspace_id,
        entries=entries,
        mirrored_servers=frozenset(mirrored_servers),
    )
