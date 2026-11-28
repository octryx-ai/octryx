"""The ``binding_config`` and ``policy_config`` a mirror run stores on a Workspace binding of an MCP resource or
prompt, and on the per-server mirror-history marker. The key formats are in ``mcp_governance.resource_identity``."""

from typing import Literal, NotRequired, TypedDict

McpResourceRisk = Literal["read", "write", "admin", "unknown"]
LifecycleState = Literal["active", "missing"]


class MirrorRejection(TypedDict):
    reason: str  # ``[<code>]`` or ``[<field>:<code>]``, never provider text
    detectedAt: str


class MirroredBindingConfig(TypedDict):
    serverName: str
    resourceIdentity: NotRequired[str]  # a resource's sha256 identity digest
    resourceUri: NotRequired[str]  # a resource's governed URI, never the advertised one
    promptName: NotRequired[str]
    contractDigest: str  # the digest an admin approved by enabling the binding
    mirroredAt: str
    lifecycleState: LifecycleState
    # A review is open while reviewState is set: the binding stays disabled until an admin enables it again.
    reviewState: NotRequired[Literal["needs_review"]]
    previousContractDigest: NotRequired[str]
    driftDetectedAt: NotRequired[str]
    reappearedAt: NotRequired[str]
    missingDetectedAt: NotRequired[str]
    mirrorRejection: NotRequired[MirrorRejection]


class MirroredPolicyConfig(TypedDict):
    risk: McpResourceRisk  # admin-owned metadata, never inferred
    source: Literal["mcp_resource_mirror"]


class MirrorMarkerConfig(TypedDict):
    serverName: str
    mirrorScope: Literal["server"]
    mirroredAt: str
    entryCount: int


class MirrorMarkerPolicy(TypedDict):
    source: Literal["mcp_resource_mirror"]
    mirrorScope: Literal["server"]


__all__ = [
    "LifecycleState",
    "McpResourceRisk",
    "MirrorMarkerConfig",
    "MirrorMarkerPolicy",
    "MirrorRejection",
    "MirroredBindingConfig",
    "MirroredPolicyConfig",
]
