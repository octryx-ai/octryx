"""The companion's queue (Octryx companion, stage 1).

- ``GET /api/v1/attention``: what needs the signed-in person, each entry with the exact requests that answer it
  (``services.attention``), and their runs for the companion's arms;
- ``GET /api/v1/attention/jobs?scope=mine|team&workspace_id=``: the person's or their Workspaces' runs;
- ``GET /api/v1/attention/jobs/{run_id}``: a read-only watch view (phases, current step, run events);
- ``POST /api/v1/attention/dismiss`` ``{key}``: hide a finished entry ("Done");
- ``WS /api/v1/attention/ws``: per-person nudges, authenticated by the session cookie (no token in the URL) and
  accepted only from the platform's own origins; ``{"watch": run_id}`` adds ``job_changed`` nudges for a run the
  person may read, ``{"unwatch": run_id}`` ends them.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...db import get_db
from ...models import User, WorkflowRun
from ...schemas.core.workspace_ref import WorkspaceId
from ...services.access_control import require_visible_workspace
from ...services.attention.dismissals import dismiss, dismissible
from ...services.attention.jobs import SCOPES, job_detail, job_list
from ...services.attention.service import attention
from ...services.attention.stream import user_stream_manager
from ...services.auth import decode_token, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/attention", tags=["attention"])


class DismissRequest(BaseModel):
    key: str = Field(min_length=1, max_length=120)


@router.get("")
async def get_attention(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await attention(db, current_user)


@router.get("/jobs")
async def get_jobs(scope: str = Query(default="mine", max_length=10),
                   workspace_id: str | None = Query(default=None, max_length=36),
                   current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if scope not in SCOPES:
        raise HTTPException(status_code=422, detail={"code": "invalid_scope", "message": "scope is mine or team."})
    return {"jobs": await job_list(db, current_user, scope=scope, workspace_id=workspace_id)}


async def _readable_run(db: AsyncSession, run_id: str, user: User) -> WorkflowRun | None:
    from ...services.workflow_runs.access import run_access

    run = await db.get(WorkflowRun, run_id)
    return run if run is not None and await run_access(db, run, user) in ("read", "write") else None


@router.get("/jobs/{run_id}")
async def get_job(run_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await _readable_run(db, run_id, current_user)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_run", "message": "Unknown run."})
    return await job_detail(db, run, current_user)


class FixtureRequest(BaseModel):
    workspace_id: WorkspaceId = Field(min_length=1, max_length=36)


@router.post("/test-fixtures")
async def post_test_fixtures(body: FixtureRequest, current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """Acceptance fixtures (a question, a gate, a problem, a finished run) in a test Workspace; admins outside
    production only, harmless to answer (no model turn)."""
    from ...services.attention.fixtures import FIXTURES_FLAG, FixtureError, fixtures_enabled, generate
    from ...services.workflow_runs.records import WorkflowRunError

    if not fixtures_enabled():  # only where the deployment sets the flag explicitly
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": f"{FIXTURES_FLAG} is off."})
    await require_visible_workspace(db, current_user.id, body.workspace_id)
    try:
        created = await generate(db, current_user, workspace_id=body.workspace_id)
    except FixtureError as error:
        raise HTTPException(status_code=403, detail={"code": str(error), "message": "Not available."}) from error
    except WorkflowRunError as error:
        raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": str(error)}) \
            from error
    await db.commit()
    return created


class FixtureHandoverResponse(BaseModel):
    run_id: str = Field(min_length=1, max_length=36)
    action: str = Field(pattern="^(accept|decline)$")


@router.post("/test-fixtures/handover-response")
async def post_fixture_handover_response(body: FixtureHandoverResponse,
                                         current_user: User = Depends(get_current_user),
                                         db: AsyncSession = Depends(get_db)):
    """Acceptance only: the stub fixture member accepts or declines a handover addressed to it (flag, admin)."""
    from ...services.attention.fixtures import FIXTURES_FLAG, FixtureError, fixtures_enabled, member_handover_response
    from ...services.workflow_runs.records import WorkflowRunError

    if not fixtures_enabled():
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": f"{FIXTURES_FLAG} is off."})
    try:
        result = await member_handover_response(db, current_user, run_id=body.run_id, action=body.action)
    except FixtureError as error:
        raise HTTPException(status_code=403, detail={"code": str(error), "message": "Not available."}) from error
    except WorkflowRunError as error:
        raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": str(error)}) \
            from error
    await db.commit()
    return result


@router.post("/dismiss")
async def dismiss_entry(body: DismissRequest, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    if not dismissible(body.key):
        raise HTTPException(status_code=422, detail={"code": "not_dismissible",
                                                     "message": "Only finished entries can be dismissed."})
    await dismiss(db, current_user, body.key)
    await db.commit()
    return {"dismissed": body.key}


def _allowed_origins() -> set[str]:
    settings = get_settings()
    origins = {item.strip().rstrip("/") for item in str(settings.cors_allowed_origins or "").split(",") if item.strip()}
    if settings.platform_public_origin:
        origins.add(str(settings.platform_public_origin).rstrip("/"))
    return origins


@router.websocket("/ws")
async def attention_ws(websocket: WebSocket):
    origin = str(websocket.headers.get("origin") or "").rstrip("/")
    if origin and origin not in _allowed_origins():
        await websocket.close(code=1008, reason="Origin not allowed")
        return
    token = str(websocket.cookies.get("access_token") or "").strip()
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return
    try:
        user_id = decode_token(token)
    except HTTPException as exc:
        await websocket.close(code=1008, reason=str(exc.detail))
        return
    await user_stream_manager.connect(user_id, websocket)
    try:
        while True:
            message = await websocket.receive_json()  # {"watch": run_id}: job_changed nudges for a readable run
            message = message if isinstance(message, dict) else {}
            if unwatch := str(message.get("unwatch") or "")[:36]:
                await user_stream_manager.unwatch(unwatch, websocket)
            run_id = str(message.get("watch") or "")[:36]
            if run_id and await _may_watch(user_id, run_id):
                await user_stream_manager.watch(run_id, websocket)
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        await user_stream_manager.unwatch_all(websocket)
        await user_stream_manager.disconnect(user_id, websocket)


async def _may_watch(user_id: str, run_id: str) -> bool:
    from ...db import core as db_core

    async with db_core.async_session_factory() as db:
        user = await db.get(User, user_id)
        return user is not None and await _readable_run(db, run_id, user) is not None
