from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ...core.workspace_ref import OptionalWorkspaceId, WorkspaceId


class BudgetPolicyUpsertRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    user_id: str | None = None
    project_id: OptionalWorkspaceId = None
    daily_request_limit: int | None = Field(default=None, ge=0)
    daily_token_limit: int | None = Field(default=None, ge=0)
    daily_cost_limit: float | None = Field(default=None, ge=0)
    warn_at_percent: int = Field(default=80, ge=1, le=1000)
    block_at_percent: int = Field(default=100, ge=1, le=1000)
    is_active: bool = True


class CostAllocationRuleUpsertRequest(BaseModel):
    id: str | None = None
    project_id: WorkspaceId = Field(min_length=1)
    cost_center: str = Field(min_length=1)
    percentage: float = Field(ge=0.01, le=100)
    valid_from: str = Field(min_length=10)


class ExportPackageCreateRequest(BaseModel):
    package_type: Literal["agent", "skill", "task"]
    entity_id: str = Field(min_length=1)


class ImportPackageCreateRequest(BaseModel):
    package_id: str | None = Field(default=None, min_length=1)
    package_json: dict[str, Any] | None = None
    overwrite_existing: bool = False
    target_project_id: OptionalWorkspaceId = Field(default=None, min_length=1)
    name_override: str | None = Field(default=None, min_length=1)


class ReportExportCreateRequest(BaseModel):
    report_type: Literal[
        "cost_summary",
        "team_activity",
        "agent_performance",
        "incident_resolution",
        "knowledge_coverage",
    ]
    format: Literal["json", "csv", "pdf"] = "json"
    parameters: dict[str, Any] = Field(default_factory=dict)


class IdentityProviderUpsertRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    provider_type: str = "oidc"
    issuer_url: str | None = None
    discovery_url: str | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    userinfo_endpoint: str | None = None
    jwks_uri: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    claim_mappings: dict[str, Any] = Field(default_factory=dict)
    group_role_mappings: dict[str, Any] = Field(default_factory=dict)
    group_group_mappings: dict[str, Any] = Field(default_factory=dict)
    default_roles: list[str] = Field(default_factory=list)
    default_group_ids: list[str] = Field(default_factory=list)
    auto_provision_users: bool = True
    is_active: bool = True


class StoredSecretMetadataUpdateRequest(BaseModel):
    expires_at: datetime | None = None


class SecretRotateRequest(BaseModel):
    value: str = Field(min_length=1)
    expires_at: datetime | None = None
    note: str = ""


class SecretRevokeRequest(BaseModel):
    note: str = ""


class FeatureFlagUpsertRequest(BaseModel):
    key: str = Field(min_length=1)
    description: str = ""
    enabled: bool = False
    rollout_percentage: int = Field(default=100, ge=0, le=100)
    allowed_projects: list[str] = Field(default_factory=list)
    allowed_roles: list[str] = Field(default_factory=list)
