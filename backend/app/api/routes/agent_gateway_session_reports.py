"""What the launcher's hooks report from a running session: the seat reviewer's call and answer, the local tool
audit, lessons learned, the Stop verification and the session's end.

Included into the ``/api/v1/agent-gateway`` router by ``agent_gateway.py``; this router has no prefix of its own.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_board.claim_values import KIND_GATEWAY_SESSION, RELEASE_SESSION_STOPPED

from ...db import async_session_factory, get_db
from ...services.agent_board.claims import release_holder_claims
from ...services.agent_board.handoff_trigger import safe_handoff_now
from ...services.agent_board.reading import unread_for_agent
from ...services.agent_board.session_hints import session_handoff_hints
from ...services.agent_gateway.codex_exec_evidence import codex_exec_evidence, with_literal_hint
from ...services.agent_gateway.contract import STATE_DENIED, STATE_NEEDS_CONFIGURATION
from ...services.agent_gateway.finalize import finalize_gateway_session
from ...services.agent_gateway.identity import GatewayRefusal
from ...services.agent_gateway.policy import load_workspace_policy
from ...services.agent_gateway.presence import session_key_hash, stop_presence
from ...services.agent_gateway.session_activity import ACTIVITY_WAITING, ACTIVITY_WORKING, note_activity
from ...services.agent_gateway.tool_execution import STATE_RECORDED
from ...services.agent_gateway.turn_capture import CAPTURE_SCHEDULED, turn_capture_state
from ...services.agent_gateway.verification import evaluate_verification, session_tool_calls
from ...services.content_routing.client_conversation import note_conversation, route_answer
from ...services.knowledge.memory.auto_capture import run_turn_memory_capture
from ...services.prompt_catalog import prompt_set_scope
from ...services.prompt_catalog.out_of_turn import prompt_set_for
from ...services.workflow_runs.gateway_tests import record_gateway_tests
from ...services.workflow_runs.octryx.hooks import session_contract, test_prefixes
from ...services.workflow_runs.octryx.stop import run_stop
from ._agent_gateway_http import (
    REASON_HOOK_EVENT_UNSUPPORTED,
    REASON_POLICY_INVALID,
    _bounded_json,
    _from_refusal,
    _identity_and_session,
    _refusal,
)

router = APIRouter()

# Carries the pass's whole change (facts.MAX_PATCH, 64 MB; a binary patch is base85 with newlines, JSON adds
# little) plus the facts around it.
MAX_VERIFICATION_BODY_BYTES = 96 * 1024 * 1024
# A finalize body carries the bounded transcript digest.
MAX_FINALIZE_BODY_BYTES = 512 * 1024
END_REASON_CLEAR = "clear"
_VERIFICATION_EVENTS = frozenset({"Stop", "SubagentStop"})
MAX_REVIEW_ANSWER_BODY_BYTES = 512 * 1024


@router.get("/review-request")
async def review_request(request: Request, db: AsyncSession = Depends(get_db)):
    """The independent reviewer's pending call for this seat session's device job (``workflow_runs.review.seat``):
    ``{turn_id, system, user, images: [{name, media_type, data}], model, engine}``. Only the session the device
    registered for that job reads it; 404 when it has none."""
    from ...services.workflow_runs.review.seat_control import review_request_for

    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    identity, session = resolved
    pending = await review_request_for(db, session, identity.user.id)
    await db.commit()
    if pending is None:
        return _refusal(STATE_DENIED, "review_request_not_found", 404)
    return JSONResponse(pending, headers={"cache-control": "no-store"})


@router.post("/review-answer")
async def review_answer(request: Request, db: AsyncSession = Depends(get_db)):
    """The device's answer to the reviewer's call: ``{turn_id, text, usage: {input_tokens, output_tokens}, model}``."""
    from ...services.workflow_runs.review.seat_control import store_review_answer

    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    identity, session = resolved
    body = await _bounded_json(request, MAX_REVIEW_ANSWER_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    refused = await store_review_answer(db, session, identity.user.id, body)
    if refused:
        await db.rollback()
        return _refusal(STATE_DENIED, refused, 404 if refused == "review_request_not_found" else 409)
    await db.commit()
    return {"state": "recorded"}


MAX_TOOL_AUDIT_BODY_BYTES = 4 * 1024 * 1024


@router.post("/sessions/tool-audit")
async def tool_audit(request: Request, db: AsyncSession = Depends(get_db)):
    """The launcher's batch of local tool decisions and execution evidence (``agent_gateway.tool_audit``):
    body ``{events: [...]}``; answers the counts and the session's run contract, so a
    paused or waiting run reaches the next local decision."""
    from ...services.agent_gateway.tool_audit import record_tool_audit  # noqa: PLC0415

    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    identity, session = resolved
    body = await _bounded_json(request, MAX_TOOL_AUDIT_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    counts = await record_tool_audit(db, session=session, events=body.get("events"))
    contract = await session_contract(db, session)
    await note_activity(db, identity.session_key, ACTIVITY_WORKING)
    await db.commit()
    return {"state": STATE_RECORDED, **counts, **({"workflow_run": contract} if contract else {})}


MAX_LESSONS_BODY_BYTES = 64 * 1024


@router.post("/sessions/lessons")
async def session_lessons(request: Request, db: AsyncSession = Depends(get_db)):
    """Lessons learned for the team from this session (``knowledge/memory/session_lessons``).

    The Workspace is the session's own (the gateway identity), never a body field. Body: ``{ref, facts, summary}``,
    redacted by the client; the server redacts again. Answers ``{state, proposed?}``; ``off`` when the Workspace did
    not switch it on.
    """
    from ...services.knowledge.memory.session_lessons import capture_session_lessons  # noqa: PLC0415

    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    identity, session = resolved
    body = await _bounded_json(request, MAX_LESSONS_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    if session.parent_session_id or (session.sub_agent_depth or 0) > 0:
        return JSONResponse({"state": "skipped", "reason": "sub_agent_session"})
    result = await capture_session_lessons(db, user_id=str(identity.user.id), workspace_id=identity.workspace_id,
                                           session_id=session.id, ref=body.get("ref"), facts=body.get("facts"),
                                           summary=body.get("summary"))
    await db.commit()
    return JSONResponse(result, headers={"cache-control": "no-store"})


@router.post("/sessions/verification")
async def verification(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    identity, session = resolved
    body = await _bounded_json(request, MAX_VERIFICATION_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    hook_event = body.get("hook_event_name")
    if hook_event not in _VERIFICATION_EVENTS:
        return _refusal(STATE_NEEDS_CONFIGURATION, REASON_HOOK_EVENT_UNSUPPORTED, 400)
    loaded = await load_workspace_policy(db, identity.workspace_id)
    if loaded.policy is None:
        return _refusal(STATE_NEEDS_CONFIGURATION, loaded.reason or REASON_POLICY_INVALID, 409)
    tool_calls = await session_tool_calls(db, session.id)
    # Codex code mode only (``None`` for every other engine): inner exec calls matched to the gateway's exec input.
    exec_evidence = codex_exec_evidence(session, tool_calls)
    if exec_evidence is not None:
        tool_calls = exec_evidence.rows
    with prompt_set_scope(await prompt_set_for(db, workspace_id=identity.workspace_id)):
        setup = body.get("test_setup")  # the client's finding: does the folder have tests at all
        result = evaluate_verification(loaded.policy, tool_calls,
                                       test_setup=setup if isinstance(setup, bool) else None)
    # A session bound to a workflow run reports its newest test run's per-test results to the run, then the
    # run's current phase decides the stop instead of the Workspace test gate: only the server advances.
    await record_gateway_tests(db, session_id=session.id, policy=loaded.policy, tool_calls=tool_calls)
    run_answer = await run_stop(db, session=session, hook_input=body, tool_calls=tool_calls,
                                test_prefixes=test_prefixes(loaded.policy))
    capture = await turn_capture_state(db, session=session, hook_event=str(hook_event), verification_state=result.state)
    if capture == CAPTURE_SCHEDULED:
        background_tasks.add_task(run_turn_memory_capture, session_factory=async_session_factory, session_id=session.id)
    # Pull-only board delivery: a count, never a body; the Stop hook turns it into one line.
    agent_hash = session_key_hash(identity.session_key)
    unread = await unread_for_agent(db, agent_hash=agent_hash, user_id=identity.user.id,
                                    project_id=identity.workspace_id)
    # Items other agents hand off (when this session has spare allowance) and this session's handoff nudges.
    handoffs = await session_handoff_hints(db, session_key=identity.session_key, agent_hash=agent_hash,
                                           project_id=identity.workspace_id)
    route = await route_answer(db, session.id, note_conversation(session, body))  # terminal notice
    trigger = await safe_handoff_now(db, session_key=identity.session_key)  # hand over at the trigger
    mobile = body.get("mobile") if isinstance(body.get("mobile"), dict) else {}
    # A subagent's end is not the turn's end: only the main Stop means the session waits for the person.
    await note_activity(db, identity.session_key,
                        ACTIVITY_WAITING if hook_event == "Stop" else ACTIVITY_WORKING,
                        title=mobile.get("title"), last_text=mobile.get("last_text"))
    await db.commit()
    answer = run_answer or result.to_payload()
    if exec_evidence is not None:
        answer = with_literal_hint(answer, exec_evidence)
    return {**answer, "policy_source": loaded.source, "memory_capture": capture,
            "unread_for_me": unread, **handoffs, **trigger, **route}


@router.post("/sessions/finalize")
async def finalize(request: Request, db: AsyncSession = Depends(get_db)):
    resolved = await _identity_and_session(request, db)
    if isinstance(resolved, GatewayRefusal):
        return _from_refusal(resolved)
    identity, session = resolved
    body = await _bounded_json(request, MAX_FINALIZE_BODY_BYTES)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    if body.get("end_reason") == END_REASON_CLEAR:
        # /clear ends a conversation, not the session: nothing stops, nothing is revoked, and the
        # session is not marked ended. The launcher does not finalize on clear; this guards any caller that does.
        return {"state": "kept_alive", "reason": END_REASON_CLEAR}
    # The session ends: presence ``stopped`` and the seat credential revoked, committed with finalize.
    await stop_presence(db, identity.session_key)
    # Its work-item claims end with it; a /clear above keeps them.
    await release_holder_claims(
        db, kind=KIND_GATEWAY_SESSION, ref_hash=session_key_hash(identity.session_key), reason=RELEASE_SESSION_STOPPED
    )
    return await finalize_gateway_session(db, session=session, identity=identity, body=body)
