from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectRepoQualityUpdateRequest(BaseModel):
    repo_code_quality: dict[str, Any] = Field(default_factory=dict)


class ProjectRuntimePolicyUpdateRequest(BaseModel):
    runtime_policy: dict[str, Any] = Field(default_factory=dict)


class ProjectRepositoryOperationPolicyRequest(BaseModel):
    repository_id: str = Field(min_length=1)
    operations: dict[str, bool] = Field(default_factory=dict)


class ProjectKnowledgeMountRequest(BaseModel):
    source_project_id: str = Field(min_length=1)
    mount_label: str = ""


class ProjectResourceAssignmentsUpdateRequest(BaseModel):
    repository_policies: list[ProjectRepositoryOperationPolicyRequest] = Field(default_factory=list)
    knowledge_access: dict[str, Any] | None = None
    knowledge_mounts: list[ProjectKnowledgeMountRequest] = Field(default_factory=list)


class ProjectRepositoryBootstrapUpdateRequest(BaseModel):
    repository_bootstrap: dict[str, Any] = Field(default_factory=dict)


class WorkspaceCompositionBindingUpdateRequest(BaseModel):
    display_name: str | None = None
    binding_status: Literal["active", "hidden"] | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None
    intent_scopes: list[str] | None = None
    binding_config: dict[str, Any] | None = None
    policy_config: dict[str, Any] | None = None


class WorkspacePolicyUpdateRequest(BaseModel):
    default_bindings: dict[str, str] | None = None
    routing_policy: dict[str, Any] | None = None
    delegation_policy: dict[str, Any] | None = None
    runtime_policy: dict[str, Any] | None = None


class WorkspaceAssignmentControlsUpdateRequest(BaseModel):
    agent_assignment_mode: Literal["all_installed", "selected_only"] | None = None
    runtime_assignment_mode: Literal["all_installed", "selected_only"] | None = None
    default_agent_binding_key: str | None = None
    default_runtime_binding_key: str | None = None


class ProjectSkillAssignmentsUpdateRequest(BaseModel):
    assignment_mode: Literal["all_active", "selected_only", "none"] | None = None
    selected_skill_ids: list[str] = Field(default_factory=list)
    blocked_skill_ids: list[str] = Field(default_factory=list)
