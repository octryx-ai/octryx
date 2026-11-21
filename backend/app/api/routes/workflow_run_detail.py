"""One workflow run: its view, events and screenshots, the actions on it, and the session it continues in.

Included into the ``/api/v1/workflow-runs`` router by ``workflow_runs.py``; this router has no prefix of its own.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User, WorkflowRun
from ...services.auth import get_current_user
from ...services.workflow_runs.access import require_run, require_run_action
from ...services.workflow_runs.actions import ACTION_RESUME_IN_NEW_SESSION, perform_action
from ...services.workflow_runs.octryx.new_thread import continue_in_new_thread
from ...services.workflow_runs.records import WorkflowRunError, bind_session
from ...services.workflow_runs.run_lists import run_events
from ...services.workflow_runs.run_sessions import run_for_session
from ._workflow_run_http import BindSessionRequest, RunActionRequest, _http, _own_session, _refused, _view

logger = logging.getLogger(__name__)
SCREENS_TIMEOUT = 5.0  # seconds a run's screenshot folder may take to read
router = APIRouter()


@router.get("/by-session/{session_id}")
async def run_of_session(
    session_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _own_session(db, session_id, current_user)
    run = await run_for_session(db, session_id)
    return {"run": await _view(db, run, current_user) if run is not None else None}


@router.get("/{run_id}")
async def get_run(run_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        run = await require_run(db, run_id, current_user)
    except WorkflowRunError as error:
        raise _http(error) from error
    return {"run": await _view(db, run, current_user)}


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    try:
        run = await require_run(db, run_id, current_user)
    except WorkflowRunError as error:
        raise _http(error) from error
    return await run_events(db, run, user=current_user)


async def _pass_screens(db: AsyncSession, run: WorkflowRun) -> tuple[str, list[Any]]:
    """The current pass's screenshots: ``review.screens.collect`` with the review node's ``config.phase`` (the
    changing phase, e.g. ``implement``), not the review node's id; the folder is per pass and cleared on a new entry."""
    import asyncio

    from ...services.workflow_runs.graph import graph_for_run
    from ...services.workflow_runs.review.screens import collect, reviewed_phase

    phase = reviewed_phase(run, await graph_for_run(db, run))
    # The folder is read off the event loop and given a few
    # seconds; a store that hangs (a stalled mount) shows no screenshots instead of holding the request and the loop.
    try:
        return phase, await asyncio.wait_for(asyncio.to_thread(collect, run, phase), timeout=SCREENS_TIMEOUT)
    except (OSError, TimeoutError):
        return phase, []


@router.get("/{run_id}/screens")
async def get_run_screens(
    run_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """The system tests' screenshots of the run's current pass (shown on the decision card); readers of the run."""
    try:
        run = await require_run(db, run_id, current_user)
    except WorkflowRunError as error:
        raise _http(error) from error
    node_id, screens = await _pass_screens(db, run)
    return {"screens": [{"name": item.name, "media_type": item.media_type, "size": len(item.data),
                         "node_id": node_id} for item in screens]}


@router.get("/{run_id}/screens/{name}")
async def get_run_screen(
    run_id: str, name: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """One screenshot's bytes; only a name the listing shows is served (no paths)."""
    from fastapi import Response

    if not name or name != Path(name).name or name.startswith(".") or "\\" in name:
        raise HTTPException(status_code=400, detail={"code": "invalid_name", "message": "Invalid screenshot name."})
    try:
        run = await require_run(db, run_id, current_user)
    except WorkflowRunError as error:
        raise _http(error) from error
    screen = next((item for item in (await _pass_screens(db, run))[1] if item.name == name), None)
    if screen is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_screen", "message": "No such screenshot."})
    return Response(content=screen.data, media_type=screen.media_type,
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                             "Content-Disposition": "inline"})


@router.post("/{run_id}/actions")
async def post_run_action(
    run_id: str, body: RunActionRequest, current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Continue +k, change the plan, abort, take the run over (``take_over``: become its responsible person), or
    decide what the run waits for; the run checks it again."""
    if body.action == ACTION_RESUME_IN_NEW_SESSION:
        # Offered in ``run.actions`` like every other action (so the API never refuses it as unknown_action); it
        # is the same as POST /{run_id}/sessions without a session and answers with the new chat's id.
        return await bind_run_session(run_id, BindSessionRequest(), current_user, db)
    try:
        run = await require_run_action(db, run_id, current_user, body.action)
        await perform_action(db, run, user=current_user, body=body.model_dump(exclude_none=True))
    except WorkflowRunError as error:
        raise await _refused(db, error) from error
    await db.commit()
    # A continued Action-started run gets its next phase turn from the Action (no-op for every other run).
    from ...services.workflow_runs.automation import redrive_action_turn

    try:
        await redrive_action_turn(db, run)
    except Exception:  # the decision is committed; a failed re-drive is logged and leaves the run's marker
        logger.warning("workflow_run.action_redrive_error run_id=%s", run.id, exc_info=True)
        await db.rollback()
    return {"run": await _view(db, run, current_user)}


@router.post("/{run_id}/sessions")
async def bind_run_session(
    run_id: str, body: BindSessionRequest, current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume the run in a session: the given one of the requester's, or a new chat session."""
    try:
        run = await require_run(db, run_id, current_user, write=True)
        if run.requested_by != current_user.id:
            raise WorkflowRunError("not_requester", "Only the requester continues a run in their chat.", 403)
        if body.session_id:
            session = await _own_session(db, body.session_id, current_user)
            await bind_session(db, run, session, actor_id=current_user.id)
        else:
            # A device run's current pass gets its turn again in the new chat (a refused turn is recovered so).
            session = await continue_in_new_thread(db, run, current_user)
    except WorkflowRunError as error:
        raise _http(error) from error
    await db.commit()
    return {"run": await _view(db, run, current_user), "session_id": session.id}
