"""Agent gateway: a launcher's workspace preparation report (environment
readiness) and the run's branch as a git bundle for a device that cannot fetch from origin.

Transport only: ``POST sessions/workspace-preparation`` resolves the gateway identity and session, reads a bounded
JSON report (branch checkout, readiness probes, the declared setup it ran) and answers the readiness state with the
refreshed run contract. The decision lives in ``services/workflow_runs/workspace``.

``POST sessions/branch-bundle`` (body ``{"have": [<commit>, ...]}``) answers the branch of the run the session is
bound to as a git bundle from the platform's working copy (``workspace/branch_bundle``).

``POST sessions/work-git`` (body: the launcher's ``work_git`` report — ``node_id``, ``entry``, ``seq``, ``results``
per op, ``change``) records the teamwork git work the main thread's launcher ran (``teamwork/device_items``): branched
items start, merges reach the scheduler, the main folder's change becomes ``device_change``. Only the run's main
``octryx`` session reports it; an item's session is refused.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.agent_gateway.contract import STATE_DENIED, STATE_NEEDS_CONFIGURATION
from ...services.agent_gateway.identity import GatewayRefusal, resolve_gateway_identity
from ...services.agent_gateway.sessions import find_gateway_session
from ...services.workflow_runs.records import active_run_for_session
from ...services.workflow_runs.workspace.branch_bundle import branch_bundle
from ...services.workflow_runs.workspace.gateway import REASON_NO_RUN, report_preparation
from ._agent_gateway_http import _bounded_json, _from_refusal, _refusal

router = APIRouter(prefix="/api/v1/agent-gateway/sessions", tags=["agent-gateway"])

MAX_REPORT_BODY_BYTES = 128 * 1024
# The device names its commits (its HEAD and branch tips); the bound only keeps a request body finite.
MAX_HAVE_BODY_BYTES = 4 * 1024 * 1024
# The report carries the story's whole change as a patch (``octryx.facts.MAX_PATCH``, JSON-escaped) plus the op
# results; the bound only keeps a request body finite.
MAX_WORK_GIT_BODY_BYTES = 96 * 1024 * 1024
REASON_ITEM_SESSION = "work_git_from_item_session"


@router.post("/workspace-preparation")
async def workspace_preparation(request: Request, db: AsyncSession = Depends(get_db)):
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _from_refusal(identity)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return _from_refusal(session)
    body = await _bounded_json(request, MAX_REPORT_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    answer = await report_preparation(db, session=session, payload=body)
    if answer is None:
        return _refusal(STATE_NEEDS_CONFIGURATION, REASON_NO_RUN, 409)
    await db.commit()
    return answer


@router.post("/branch-bundle")
async def branch_bundle_for_device(request: Request, db: AsyncSession = Depends(get_db)):
    """Only the run this session is bound to (and active): the device executes it."""
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _from_refusal(identity)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return _from_refusal(session)
    body = await _bounded_json(request, MAX_HAVE_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    run = await active_run_for_session(db, session.id)
    if run is None:
        return _refusal(STATE_NEEDS_CONFIGURATION, REASON_NO_RUN, 409)
    have = body.get("have") if isinstance(body.get("have"), list) else []
    return await branch_bundle(run, have)


@router.post("/work-git")
async def work_git_report(request: Request, db: AsyncSession = Depends(get_db)):
    """The main thread's launcher ran the run's git work (teamwork design, section 4)."""
    from app.services.workflow_runs.teamwork.work_git import work_git_reported

    from ...services.workflow_runs.octryx.contract import run_contract, session_principal
    from ...services.workflow_runs.records import lock_run
    from ...services.workflow_runs.teamwork import item_marker

    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _from_refusal(identity)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return _from_refusal(session)
    body = await _bounded_json(request, MAX_WORK_GIT_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    run = await active_run_for_session(db, session.id)
    if run is None:
        return _refusal(STATE_NEEDS_CONFIGURATION, REASON_NO_RUN, 409)
    if (marker := item_marker(session)) is not None and not marker.get("sequential"):
        return _refusal(STATE_DENIED, REASON_ITEM_SESSION, 403)
    run = await lock_run(db, run)
    state = await work_git_reported(db, run, body)
    contract = await run_contract(db, run, principal=await session_principal(db, session), session=session)
    await db.commit()
    return {"state": state, "workflow_run": contract}


MAX_COMPACTION_BODY_BYTES = 4 * 1024


@router.post("/compaction")
async def compaction_report(request: Request, db: AsyncSession = Depends(get_db)):
    """A launcher's PreCompact / PostCompact (body ``{stage, trigger, summary_chars?}``) as its run's event
    (``workflow_runs/octryx/compaction``); a session outside a run is answered ``no_run``."""
    from ...services.workflow_runs.octryx.compaction import record

    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _from_refusal(identity)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return _from_refusal(session)
    body = await _bounded_json(request, MAX_COMPACTION_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    run = await active_run_for_session(db, session.id)
    if run is None:
        return {"state": "no_run"}
    answer = await record(db, run, session.id, body)
    await db.commit()
    return answer
