from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...core.workspace_ref import OptionalWorkspaceId, WorkspaceId


class ConnectorSaveRequest(BaseModel):
    is_active: bool | None = None
    policy_active: bool | None = None
    tool_policy: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


class DatabaseConnectorRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    db_type: str = "postgresql"
    project_id: OptionalWorkspaceId = None
    is_active: bool = True
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    dsn: str | None = None
    driver: str | None = None
    ssl: bool | None = None
    file_path: str | None = None
    query_options: dict[str, Any] = Field(default_factory=dict)


class DatabaseConnectorUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    db_type: str | None = None
    project_id: OptionalWorkspaceId = None
    is_active: bool | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    dsn: str | None = None
    driver: str | None = None
    ssl: bool | None = None
    file_path: str | None = None
    clear_password: bool | None = None
    clear_dsn: bool | None = None
    query_options: dict[str, Any] | None = None


class DatabaseQueryToolRequest(BaseModel):
    connector_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    display_name: str = ""
    description: str = ""
    sql_template: str = Field(min_length=1)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    row_level_security_rules: list[str] = Field(default_factory=list)
    allowed_roles: list[str] = Field(default_factory=list)
    project_id: OptionalWorkspaceId = None
    max_rows: int = 100
    timeout_seconds: int = 30
    is_active: bool = True


class DatabaseQueryToolUpdateRequest(BaseModel):
    connector_id: str | None = None
    tool_name: str | None = None
    display_name: str | None = None
    description: str | None = None
    sql_template: str | None = None
    parameters_schema: dict[str, Any] | None = None
    row_level_security_rules: list[str] | None = None
    allowed_roles: list[str] | None = None
    project_id: OptionalWorkspaceId = None
    max_rows: int | None = None
    timeout_seconds: int | None = None
    is_active: bool | None = None


class MCPServerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    owner_scope: str = "workspace"
    workspace_id: OptionalWorkspaceId = None
    transport: str = "streamable-http"
    url: str = Field(min_length=1)
    description: str = ""
    auto_start: bool = False
    is_active: bool = False


class MCPCatalogInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_scope: str = "workspace"
    workspace_id: OptionalWorkspaceId = None
    name: str | None = None
    auto_start: bool | None = None
    description: str | None = None
    is_active: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)


class MCPCapabilityMirrorRequest(BaseModel):
    """Mirror one MCP server's discovered tools into a workspace capability catalog."""

    workspace_id: WorkspaceId = Field(min_length=1)
    auto_connect: bool = True


class MCPServerUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    description: str | None = None
    auto_start: bool | None = None
    is_active: bool | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)


class BrandingUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
