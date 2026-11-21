from typing import Any

from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool = True


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class ProjectConfigMergeRequest(BaseModel):
    """Partial config update — keys in body are merged into existing project.config."""

    tts: dict[str, Any] | None = None
    stt: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


class ProjectConfigResponse(BaseModel):
    id: str
    name: str
    config: dict[str, Any]
    model_config = ConfigDict(from_attributes=True)


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    config: dict[str, Any]
    is_active: bool
    source_type: str = "manual"
    template_key: str | None = None
    template_version: str | None = None
    template_metadata: dict[str, Any] | None = None
    is_system: bool = False
    # The Instance's default workspace (``services/project/default_workspace.py``).
    is_default: bool = False

    model_config = ConfigDict(from_attributes=True)
