from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ....runtime_limits import MAX_CONCURRENT_AGENTS
from ..admin_task_panel import DispatchBinding


class ResearchPolicyProfileCreateRequest(BaseModel):
    key: str = Field(min_length=3, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    initial_spec: dict[str, Any] = Field(default_factory=dict)
    initial_version_status: Literal["draft", "published"] = "draft"
    notes: str = ""


class ResearchPolicyProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    lifecycle_status: Literal["active", "archived", "draft"] | None = None
    is_active: bool | None = None


class ResearchPolicyVersionCreateRequest(BaseModel):
    spec: dict[str, Any] = Field(default_factory=dict)
    status: Literal["draft", "published", "archived"] = "draft"
    notes: str = ""


class ResearchPolicyVersionUpdateRequest(BaseModel):
    spec: dict[str, Any] | None = None
    status: Literal["draft", "published", "archived"] | None = None
    notes: str | None = None


class WorkspaceResearchPolicyUpdateRequest(BaseModel):
    profile_version_id: str | None = None
    clear_assignment: bool = False


class DesignArtifactCreateRequest(BaseModel):
    artifact_kind: str = Field(default="note", min_length=1)
    title: str = Field(min_length=1)
    status: str = "draft"
    summary: str = ""
    content_markdown: str = ""
    owner_user_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    linked_repository_ids: list[str] = Field(default_factory=list)
    depends_on_artifact_ids: list[str] = Field(default_factory=list)
    is_required: bool = False
    order_index: int = Field(default=100, ge=0, le=10000)


class DesignArtifactUpdateRequest(BaseModel):
    artifact_kind: str | None = None
    title: str | None = None
    status: str | None = None
    summary: str | None = None
    content_markdown: str | None = None
    owner_user_id: str | None = None
    metadata_json: dict[str, Any] | None = None
    linked_repository_ids: list[str] | None = None
    depends_on_artifact_ids: list[str] | None = None
    is_required: bool | None = None
    order_index: int | None = Field(default=None, ge=0, le=10000)


class DesignArtifactBootstrapRequest(BaseModel):
    include_optional: bool = False


class DesignTraceLinkCreateRequest(BaseModel):
    artifact_id: str = Field(min_length=1)
    target_type: str = Field(min_length=1)
    target_id: str | None = None
    title: str = Field(min_length=1)
    status: str = "active"
    url: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class DesignArtifactTaskCreateRequest(BaseModel):
    name: str | None = None
    description: str = ""
    task_type: str = "agent_run"
    agent_type: str = "coding"
    schedule: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    max_concurrent_agents: int = Field(default=3, ge=1, le=MAX_CONCURRENT_AGENTS)
    is_active: bool = True
    # How the created Action runs, always authored (services/admin/task/_dispatch_binding.py).
    dispatch_binding: DispatchBinding


class DesignReleaseSyncRequest(BaseModel):
    limit_per_repository: int = Field(default=30, ge=1, le=100)


class DesignCheckpointSyncRequest(BaseModel):
    limit_per_repository: int = Field(default=30, ge=1, le=100)


class DesignTraceSyncWorkflowRequest(BaseModel):
    id: str = Field(min_length=1)
    name: str | None = None
    description: str | None = None
    source_kind: str | None = None
    target_type: str | None = None
    mode: str | None = None
    is_active: bool | None = None
    providers: list[str] | None = None
    match_rules: list[str] | None = None
    limit_per_repository: int | None = Field(default=None, ge=1, le=100)


class DesignTraceSyncWorkflowListUpdateRequest(BaseModel):
    workflows: list[DesignTraceSyncWorkflowRequest] = Field(default_factory=list)


class DesignTraceSyncWorkflowRunRequest(BaseModel):
    limit_per_repository: int | None = Field(default=None, ge=1, le=100)


class DesignTraceSyncWorkflowTaskCreateRequest(BaseModel):
    task_name: str | None = None
    task_description: str = ""
    cron_expression: str = Field(min_length=5)
    scheduler_name: str | None = None
    scheduler_description: str = ""
    limit_per_repository: int | None = Field(default=None, ge=1, le=100)
    is_active: bool = True
