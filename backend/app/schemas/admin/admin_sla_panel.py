from __future__ import annotations

from pydantic import BaseModel, Field


class SLADefinitionCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    task_id: str | None = None
    agent_type: str | None = None
    max_duration_seconds: int = Field(ge=1, le=86400)
    alert_threshold: float = Field(default=0.8, gt=0, le=1)
    is_active: bool = True


class SLADefinitionUpdateRequest(BaseModel):
    name: str | None = None
    task_id: str | None = None
    agent_type: str | None = None
    max_duration_seconds: int | None = Field(default=None, ge=1, le=86400)
    alert_threshold: float | None = Field(default=None, gt=0, le=1)
    is_active: bool | None = None
