"""Agent gateway: the prompt hook of an octryx-claude session and its workflow run (DevOps workflows, octryx run UX).

Transport only. ``POST /api/v1/agent-gateway/sessions/prompt`` (body ``{"prompt"}``) answers a run-bound session
with its current run contract, and a session started for a Work item without an active run once with the workflow
proposal for its first prompt (``services/workflow_runs/octryx/launch``). Any other session gets ``{"state": "ok"}``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.agent_gateway.contract import STATE_DENIED
from ...services.agent_gateway.identity import GatewayRefusal
from ...services.workflow_runs.octryx.launch import prompt_answer
from ._agent_gateway_http import _bounded_json, _from_refusal, _identity_and_session, _refusal

router = APIRouter(prefix="/api/v1/agent-gateway/sessions", tags=["agent-gateway"])

MAX_PROMPT_BODY_BYTES = 64 * 1024


@router.post("/prompt")
async def session_prompt(request: Request, db: AsyncSession = Depends(get_db)):
    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    identity, session = resolved
    body = await _bounded_json(request, MAX_PROMPT_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    answer = await prompt_answer(db, session=session, workspace_id=identity.workspace_id,
                                 work_item_key=identity.work_item_key or "", prompt=str(body.get("prompt") or ""))
    await db.commit()
    return {"state": "ok", **answer}


MAX_SCREENSHOT_BODY_BYTES = 11_000_000  # one image (base64) of at most review.screens.MAX_BYTES plus its binding


@router.post("/screenshots")
async def session_screenshot(request: Request, db: AsyncSession = Depends(get_db)):
    """Screenshot evidence for the system tests of the run's current pass, kept for the independent review."""
    import base64
    import binascii

    from ...services.workflow_runs.records import active_run_for_session
    from ...services.workflow_runs.review.screens import store

    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    _identity, session = resolved
    body = await _bounded_json(request, MAX_SCREENSHOT_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    run = await active_run_for_session(db, session.id)
    node_id = str(body.get("node_id") or "")
    if run is None or not node_id or node_id != run.current_node_id:
        return {"state": "ignored", "reason": "not_this_pass"}
    try:
        data = base64.b64decode(str(body.get("data") or ""), validate=True)
    except (binascii.Error, ValueError):
        return {"state": "ignored", "reason": "not_base64"}
    reason = store(run, node_id=node_id, entry=body.get("entry"), name=str(body.get("name") or ""), data=data)
    return {"state": "ignored", "reason": reason} if reason else {"state": "stored"}


MAX_HANDS_ON_BODY_BYTES = 1024 * 1024  # per scenario its result, failed step and screenshot names


@router.post("/hands_on")
async def session_hands_on(request: Request, db: AsyncSession = Depends(get_db)):
    """The device's report of the run's hands-on test (``workflow_runs.hands_on``) for the current pass."""
    from ...services.workflow_runs.hands_on.step import record_report
    from ...services.workflow_runs.octryx.contract import run_contract, session_principal
    from ...services.workflow_runs.records import active_run_for_session, lock_run

    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    _identity, session = resolved
    body = await _bounded_json(request, MAX_HANDS_ON_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    run = await active_run_for_session(db, session.id)
    if run is None:
        return {"state": "ignored", "reason": "no_run"}
    run = await lock_run(db, run)
    state = await record_report(db, run, body, session_id=session.id)
    contract = await run_contract(db, run, principal=await session_principal(db, session), session=session)
    await db.commit()
    return {"state": state, "workflow_run": contract}


MAX_PIPELINE_BODY_BYTES = 16 * 1024 * 1024  # per command the output's end and the whole JUnit report


MAX_STYLE_BODY_BYTES = 2 * 1024 * 1024  # the change's counts and the formatter / linter results


@router.post("/pipeline/style")
async def session_pipeline_style(request: Request, db: AsyncSession = Depends(get_db)):
    """Fail fast: is the current pass's code style red? The device asks before its system test and skips it on
    ``blocking`` (``workflow_runs.pipeline_report.style_verdict``; read only, the pass's report is judged as always)."""
    from app.services.workflow_runs.pipeline_report import style_verdict

    from ...services.workflow_runs.records import active_run_for_session

    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    _identity, session = resolved
    body = await _bounded_json(request, MAX_STYLE_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    run = await active_run_for_session(db, session.id)
    if run is None:
        return {"state": "ignored", "blocking": False, "reason": "no_run"}
    return {"state": "ok", **style_verdict(run, body)}


@router.post("/pipeline")
async def session_pipeline(request: Request, db: AsyncSession = Depends(get_db)):
    """The device's report of the run's CI pipeline (``workflow_runs.pipeline``) for the current pass."""
    from app.services.workflow_runs.pipeline_report import record_report

    from ...services.workflow_runs.octryx.contract import run_contract, session_principal
    from ...services.workflow_runs.records import active_run_for_session, lock_run

    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    _identity, session = resolved
    body = await _bounded_json(request, MAX_PIPELINE_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    run = await active_run_for_session(db, session.id)
    if run is None:
        return {"state": "ignored", "reason": "no_run"}
    run = await lock_run(db, run)
    state = await record_report(db, run, body, session_id=session.id)
    contract = await run_contract(db, run, principal=await session_principal(db, session), session=session)
    await db.commit()
    return {"state": state, "workflow_run": contract}
