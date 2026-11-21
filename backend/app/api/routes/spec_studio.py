"""``/api/v1/workflow-runs/{run_id}/spec-studio``: the product owner's Spec Studio.

Thin transport over ``services/workflow_runs/spec_studio``. Reading needs the run's read access; a change needs write
access to the run or the right to decide its spec (the product owner a role names); approve and revise are the spec's
``decisions`` confirmation (``confirm`` / ``change``), so they are checked like every other run decision.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User, WorkflowRun
from ...services.auth import get_current_user
from ...services.workflow_runs.access import require_run, require_run_action
from ...services.workflow_runs.actions import perform_action
from ...services.workflow_runs.graph import SUBJECT_DECISIONS
from ...services.workflow_runs.records import WorkflowRunError, lock_run
from ...services.workflow_runs.spec_studio.corporate_link import StudioLockedError
from ...services.workflow_runs.spec_studio.corporate_link import refresh as refresh_corporate
from ...services.workflow_runs.spec_studio.service import change, evaluate, note_revision, revision_answer
from ...services.workflow_runs.spec_studio.state import StudioChangeError
from ...services.workflow_runs.states import STATUS_WAITING, WAITING_CONFIRMATION

router = APIRouter()


def _error(error: WorkflowRunError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "message": str(error)})


def _waiting_subject(run: WorkflowRun) -> dict[str, Any]:
    if run.status != STATUS_WAITING or run.waiting_kind != WAITING_CONFIRMATION:
        return {}
    waiting = dict(dict(run.node_state or {}).get("waiting") or {})
    return waiting if waiting.get("subject") == SUBJECT_DECISIONS else {}


def _payload(run: WorkflowRun) -> dict[str, Any]:
    view = evaluate(run)
    if view is None:
        raise HTTPException(status_code=404, detail={"code": "no_spec_studio",
                                                     "message": "This run has no Spec Studio yet."})
    waiting = _waiting_subject(run)
    return {"run_id": run.id, "title": run.title, "status": run.status, "awaiting_approval": bool(waiting),
            "payload_hash": waiting.get("payload_hash"), **view}


@router.get("/{run_id}/spec-studio")
async def get_spec_studio(run_id: str, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    try:
        run = await require_run(db, run_id, current_user)
    except WorkflowRunError as error:
        raise _error(error) from error
    if await refresh_corporate(db, run):
        await db.commit()
    return _payload(run)


async def _changing_run(db: AsyncSession, run_id: str, user: User) -> WorkflowRun:
    """Write access to the run, or the decider of its waiting spec (a product owner named by a role)."""
    try:
        return await require_run(db, run_id, user, write=True)
    except WorkflowRunError as error:
        if error.status_code != 403:
            raise
        return await lock_run(db, await require_run_action(db, run_id, user, "confirm"))


@router.patch("/{run_id}/spec-studio")
async def patch_spec_studio(run_id: str, body: dict[str, Any] = Body(...),
                            current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """One change: ``{op: answer|design|comment.add|comment.edit|comment.remove|rule|acceptance, ...}``."""
    try:
        run = await _changing_run(db, run_id, current_user)
        await refresh_corporate(db, run)
        detail = change(db, run, body, user=current_user)
    except WorkflowRunError as error:
        raise _error(error) from error
    except StudioLockedError as error:
        raise HTTPException(status_code=409, detail={"code": "locked_by_corporate", "message": str(error)}) from error
    except StudioChangeError as error:
        raise HTTPException(status_code=422, detail={"code": "invalid_change", "message": str(error)}) from error
    await db.commit()
    return {"change": detail, **_payload(run)}


async def _decide(db: AsyncSession, run_id: str, user: User, action: str) -> WorkflowRun:
    run = await require_run_action(db, run_id, user, action)
    waiting = _waiting_subject(run)
    if not waiting:
        raise WorkflowRunError("not_awaiting_approval", "The spec does not wait for approval now.", 409)
    await refresh_corporate(db, run)
    view = evaluate(run)
    if view is None:
        raise WorkflowRunError("no_spec_studio", "This run has no Spec Studio yet.", 404)
    if action == "confirm":
        await perform_action(db, run, user=user, body={"action": "confirm", "payload_hash": waiting["payload_hash"]})
    else:
        note_revision(db, run, user)
        await perform_action(db, run, user=user, body={"action": "change", "reason": revision_answer(view)})
    return run


async def _decided(db: AsyncSession, run_id: str, user: User, action: str) -> dict[str, Any]:
    from ...services.workflow_runs.automation import redrive_action_turn

    try:
        run = await _decide(db, run_id, user, action)
    except WorkflowRunError as error:
        if error.persist:
            await db.commit()
        raise _error(error) from error
    await db.commit()
    try:
        await redrive_action_turn(db, run)
    except Exception:  # committed; a failed re-drive leaves the run's marker, as on /actions
        await db.rollback()
    return _payload(run)


@router.post("/{run_id}/spec-studio/approve")
async def approve_spec_studio(run_id: str, current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """Approve: freeze version n as the review baseline, write the decisions into SPEC.md, go on to the stories."""
    return await _decided(db, run_id, current_user, "confirm")


@router.post("/{run_id}/spec-studio/revise")
async def revise_spec_studio(run_id: str, current_user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """Send the spec back to the draft phase with every decision, comment, changed value and rejected criterion."""
    return await _decided(db, run_id, current_user, "change")


@router.get("/{run_id}/spec-studio/baseline")
async def get_spec_studio_baseline(run_id: str, current_user: User = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_db)):
    """The approved version the stories are reviewed against: tokens, comments, baseline images, scenarios."""
    try:
        run = await require_run(db, run_id, current_user)
    except WorkflowRunError as error:
        raise _error(error) from error
    record = dict(dict(run.context or {}).get("spec_studio") or {})
    approved = list(record.get("approved") or [])
    if not approved:
        raise HTTPException(status_code=404, detail={"code": "not_approved", "message": "No approved spec yet."})
    return {"approved": approved[-1], "baseline": record.get("baseline") or [],
            "scenarios": record.get("scenarios") or []}


@router.get("/{run_id}/spec-studio/corporate-asset")
async def get_spec_studio_corporate_asset(run_id: str, path: str, current_user: User = Depends(get_current_user),
                                          db: AsyncSession = Depends(get_db)):
    """The CI logo or an icon of this run's corporate direction, for everyone who may read the run (the CI page's
    asset route is for admins). Only the files the run's snapshot names, inside the profile's folder."""
    from pathlib import Path

    from fastapi.responses import FileResponse

    from ...services.corp_identity_service import get_corp_identity_profile_detail
    from ...services.workflow_runs.spec_studio.corporate_link import asset_paths, snapshot

    try:
        run = await require_run(db, run_id, current_user)
    except WorkflowRunError as error:
        raise _error(error) from error
    corporate = snapshot(run)
    if corporate is None or path not in asset_paths(corporate):
        raise HTTPException(status_code=404, detail={"code": "no_asset", "message": "No such corporate asset."})
    try:
        profile = await get_corp_identity_profile_detail(db, corporate["profile_id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "no_asset", "message": "Profile gone."}) from exc
    root = Path(str(profile.get("profile_root") or "")).expanduser().resolve()
    candidate = (root / path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail={"code": "no_asset", "message": "No such corporate asset."})
    return FileResponse(str(candidate))
