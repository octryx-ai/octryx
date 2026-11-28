"""Request bodies and shared helpers of the ``/api/v1/workflow-runs`` route modules."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, User, WorkflowRun
from ....schemas.core.workspace_ref import OptionalWorkspaceId
from ....services.workflow_runs.access import run_access
from ....services.workflow_runs.records import WorkflowRunError
from ....services.workflow_runs.views import run_view


class StartRunRequest(BaseModel):
    workflow_key: str = Field(min_length=1, max_length=180)
    project_id: OptionalWorkspaceId = None
    work_item_id: str | None = None
    repository: str | None = Field(default=None, max_length=500)
    branch: str | None = Field(default=None, max_length=500)
    # The branch the run's own branch starts from (default: the repository's default branch):
    # a bug reported against an older commit, or a story on top of an unmerged one, starts there.
    base_branch: str | None = Field(default=None, max_length=200)
    # The app's folder in the repository (``workspace.spec.validate_app``); its .octryx/environment.json is the run's.
    app: str | None = Field(default=None, max_length=200)
    session_id: str | None = None
    # Where the run executes: {"kind": "server"} | {"kind": "device", device_id, folder, profile?, model?} |
    # {"kind": "terminal"}; absent: the Server (``workflow_runs.runtime_target``).
    runtime_target: dict | None = None


class BindSessionRequest(BaseModel):
    session_id: str | None = None


class RunActionRequest(BaseModel):
    # Unknown fields are refused (422), never dropped: a misnamed hint would otherwise never reach the agent.
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=40)
    k: int | None = None
    payload_hash: str | None = Field(default=None, max_length=71)
    payload: dict | None = None
    # Abort / stop: why the run stops (required there, bounded by ``stop_reason``); new_branch: the branch name the
    # requester chose; a "change" in ticket delivery: the product owner's answers to the agent (up to 8000 characters).
    reason: str | None = Field(default=None, max_length=8000)
    branch: str | None = Field(default=None, max_length=200)
    runtime_target: dict | None = None
    reply: str | None = Field(default=None, min_length=1, max_length=8000)
    # waive_hands_on_scenarios: the scenario ids (generated, e.g. "S4", or a repository "repo:…") an admin waives.
    scenarios: list[str] | None = Field(default=None, max_length=50)
    # continue / change_plan with a reason: the numbers (1-based) of earlier product owner answers it replaces.
    replaces: list[int] | None = Field(default=None, max_length=50)


class CeilingRequest(BaseModel):
    loop_ceiling: int


class WorkItemLimitsRequest(BaseModel):
    loop_limit: int | None = None
    budget: dict | None = None


def _http(error: WorkflowRunError) -> HTTPException:
    typed = {"state": error.state, "reason": error.code} if error.state else {}
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "message": str(error), **typed})


async def _refused(db: AsyncSession, error: WorkflowRunError) -> HTTPException:
    if error.persist:
        await db.commit()
    return _http(error)


async def _own_session(db: AsyncSession, session_id: str, user: User) -> Session:
    session = await db.get(Session, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "unknown_session", "message": "Unknown session."})
    return session


async def _view(db: AsyncSession, run: WorkflowRun, user: User) -> dict[str, Any]:
    return await run_view(db, run, access=await run_access(db, run, user), user=user)


def _start_context(body: StartRunRequest) -> dict[str, Any] | None:
    from ....services.workflow_runs.workspace.run_app import APP_KEY, APP_SOURCE_START, app_context, validate_app

    context: dict[str, Any] = {}
    if (body.base_branch or "").strip():
        context["base_branch"] = body.base_branch.strip()
    if body.app is not None:
        app, errors = validate_app(body.app)
        if errors:
            raise HTTPException(status_code=422, detail=errors[0])
        context[APP_KEY] = app_context(app, APP_SOURCE_START)
    return context or None
