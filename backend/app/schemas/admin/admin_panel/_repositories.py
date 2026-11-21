from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ...core.workspace_ref import OptionalWorkspaceId


class CodeRepositoryRequest(BaseModel):
    project_id: OptionalWorkspaceId = None
    name: str = Field(min_length=1)
    description: str = ""
    repo_root: str = Field(min_length=1)
    provider: str = "local"
    remote_url: str | None = None
    default_branch: str = "main"
    index_backend: str | None = None
    semantic_backend: str | None = None
    structure_backend: str | None = None
    graph_backend: str | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class CodeRepositoryUpdateRequest(BaseModel):
    project_id: OptionalWorkspaceId = None
    name: str | None = None
    description: str | None = None
    repo_root: str | None = None
    provider: str | None = None
    remote_url: str | None = None
    default_branch: str | None = None
    index_backend: str | None = None
    semantic_backend: str | None = None
    structure_backend: str | None = None
    graph_backend: str | None = None
    config_json: dict[str, Any] | None = None
    is_active: bool | None = None


class CodeRepositoryIndexRequest(BaseModel):
    force: bool = False


class GitHubRepositoryCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    owner: str | None = None
    owner_type: Literal["org", "user"] = "org"
    visibility: Literal["private", "public"] = "private"
    default_branch: str = "main"
    local_path: str | None = None
    create_readme: bool = True
    create_gitignore: bool = True
    initial_commit: bool = True
    initial_commit_message: str = "chore: initialize repository"
    register_code_repository: bool = False
    project_id: OptionalWorkspaceId = None
    index_backend: Literal["auto", "zoekt", "ripgrep"] = "auto"
    semantic_backend: Literal["auto", "scip", "lsp", "regex"] = "auto"
    structure_backend: Literal["auto", "tree-sitter", "regex"] = "auto"
    graph_backend: Literal["disabled", "auto", "code_graph", "graphify"] = "auto"
    timeout_sec: int = Field(default=300, ge=30, le=1800)

