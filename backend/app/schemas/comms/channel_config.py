from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ..core.workspace_ref import OptionalWorkspaceId


class ChannelConfigBase(BaseModel):
    plugin_id: str
    name: str
    project_id: OptionalWorkspaceId = None
    enabled: bool
    config: dict[str, Any]


class ChannelConfigUpdate(BaseModel):
    name: str | None = None
    project_id: OptionalWorkspaceId = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class ChannelConfigResponse(ChannelConfigBase):
    id: int
    project_name: str | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}
