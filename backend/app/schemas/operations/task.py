from pydantic import BaseModel, ConfigDict, Field

from ..admin.admin_task_panel import DispatchBinding
from ..core.workspace_ref import WorkspaceId


class TaskCreate(BaseModel):
    project_id: WorkspaceId
    name: str
    description: str = ""
    task_type: str = "diagnosis"
    agent_type: str = "diagnosis"
    schedule: str | None = None
    config: dict = Field(default_factory=dict)
    # How the Action runs, always authored; validated against the full state (services/admin/task/_dispatch_binding.py).
    dispatch_binding: DispatchBinding


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    schedule: str | None = None
    config: dict | None = None


class TaskResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    task_type: str
    agent_type: str
    schedule: str | None
    config: dict
    is_active: bool
    owner_id: str
    created_at: str
    dispatch_binding: str

    model_config = ConfigDict(from_attributes=True)


class TaskRunResponse(BaseModel):
    id: str
    task_id: str
    session_id: str | None
    status: str
    started_by: str
    input: dict
    output: dict | None
    error: str | None
    started_at: str | None
    completed_at: str | None
    queue_priority: int | None = None
    queued_at: str | None = None
    queue_started_at: str | None = None
    estimated_wait_seconds: int | None = None

    model_config = ConfigDict(from_attributes=True)
