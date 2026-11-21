from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.workspace_ref import OptionalWorkspaceId


class EngineeringKnowledgeBuildRunCreateRequest(BaseModel):
    # Structured pack coordinates (see services/engineering_knowledge/pack_build_request.py);
    # no prompt text is parsed for versions.
    stack_key: str = ""
    source_versions: dict[str, str] = Field(default_factory=dict)
    target_versions: dict[str, str] = Field(min_length=1)
    allow_network: bool = False
    source_overrides: dict[str, str] = Field(default_factory=dict)
    source_policy: dict[str, Any] = Field(default_factory=dict)
    freshness_policy: dict[str, Any] = Field(default_factory=dict)
    publish_policy: dict[str, Any] = Field(default_factory=dict)
    max_download_bytes: int = Field(default=50 * 1024 * 1024, ge=1, le=250 * 1024 * 1024)


class EngineeringKnowledgePackAssignmentRequest(BaseModel):
    scope_type: Literal["global", "workspace", "project", "repository"] = "global"
    scope_id: str | None = None
    workspace_id: OptionalWorkspaceId = None
    repository_id: str | None = None
    stack_key: str | None = None
    assignment_status: Literal["active", "inactive"] = "active"
    priority: int = Field(default=100, ge=1, le=1000)
    assignment_policy: dict[str, Any] = Field(default_factory=dict)


class EngineeringKnowledgePackRejectRequest(BaseModel):
    reason: str = Field(default="", max_length=2000)


class EngineeringKnowledgeGraphNodeUpsertRequest(BaseModel):
    node_type: str = Field(min_length=1, max_length=80)
    node_key: str = Field(min_length=1, max_length=300)
    display_name: str = Field(default="", max_length=500)
    summary: str = Field(default="", max_length=4000)
    status: str = Field(default="active", max_length=40)
    scope_type: Literal["global", "workspace", "project", "repository"] = "global"
    scope_id: str | None = Field(default=None, max_length=200)
    workspace_id: OptionalWorkspaceId = Field(default=None, max_length=36)
    repository_id: str | None = Field(default=None, max_length=36)
    trust_level: str = Field(default="bronze", max_length=40)
    classification: str = Field(default="internal", max_length=40)
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    aliases: list[dict[str, Any]] = Field(default_factory=list)


class EngineeringKnowledgeGraphNodeReviewRequest(BaseModel):
    action: Literal[
        "promote",
        "reject",
        "retract",
        "expire",
        "mark_non_shareable",
        "edit_metadata",
        "publish_candidate",
        "merge",
    ]
    reason: str = Field(default="", max_length=2000)
    display_name: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, max_length=40)
    trust_level: str | None = Field(default=None, max_length=40)
    classification: str | None = Field(default=None, max_length=40)
    target_node_id: str | None = Field(default=None, max_length=36)
    properties: dict[str, Any] = Field(default_factory=dict)


class EngineeringKnowledgeGraphEdgeUpsertRequest(BaseModel):
    edge_type: str = Field(min_length=1, max_length=80)
    source_node_id: str = Field(min_length=1, max_length=36)
    target_node_id: str = Field(min_length=1, max_length=36)
    status: str = Field(default="active", max_length=40)
    scope_type: Literal["global", "workspace", "project", "repository"] = "global"
    scope_id: str | None = Field(default=None, max_length=200)
    trust_level: str = Field(default="bronze", max_length=40)
    classification: str = Field(default="internal", max_length=40)
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
