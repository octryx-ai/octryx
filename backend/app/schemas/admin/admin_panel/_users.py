from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ...core.workspace_ref import OptionalWorkspaceId


class ProjectAccessAssignmentRequest(BaseModel):
    user_id: str = Field(min_length=1)
    project_role: str | None = Field(default=None, min_length=2, max_length=50)
    project_roles: list[str] = Field(default_factory=list)


class ProjectGroupAccessAssignmentRequest(BaseModel):
    group_id: str = Field(min_length=1)
    project_role: str | None = Field(default=None, min_length=2, max_length=50)
    project_roles: list[str] = Field(default_factory=list)


class ProjectRoleAccessAssignmentRequest(BaseModel):
    role_id: str = Field(min_length=1)
    project_roles: list[str] = Field(default_factory=list)


class ProjectAccessUpdateRequest(BaseModel):
    assignments: list[ProjectAccessAssignmentRequest] = Field(default_factory=list)
    group_assignments: list[ProjectGroupAccessAssignmentRequest] = Field(default_factory=list)
    role_assignments: list[ProjectRoleAccessAssignmentRequest] = Field(default_factory=list)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1)
    email: str = Field(min_length=1)
    password: str = Field(min_length=8)
    display_name: str = ""
    account_type: str = "human"
    roles: list[str] = Field(default_factory=lambda: ["viewer"])


class UserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=1)
    email: str | None = Field(default=None, min_length=1)
    display_name: str | None = None
    account_type: str | None = None
    roles: list[str] | None = None
    group_ids: list[str] | None = None
    is_active: bool | None = None


class UserPasswordResetRequest(BaseModel):
    password: str = Field(min_length=8)


class UserApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    project_id: OptionalWorkspaceId = None
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class IdentityGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    is_active: bool = True
    rls_attributes: list[dict[str, str]] = Field(default_factory=list)


class IdentityGroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    is_active: bool | None = None
    rls_attributes: list[dict[str, str]] | None = None


class RoleCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str = ""
    permissions: list[dict[str, str]] = Field(default_factory=list)


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=64)
    description: str | None = None
    permissions: list[dict[str, str]] | None = None
