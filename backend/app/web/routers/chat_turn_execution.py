"""Chat transport for the read-only turn execution summary and the workflow proposal answer."""

from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.runtime_defaults import DEFAULT_AGENT_MODE_KEY
from ...db import async_session_factory, get_db
from ...models import Session as AgentSession
from ...services.session.turn_execution_summary_service import load_user_turn_execution_summary
from ...services.workflow_routing.phased_start import (
    ANSWER_OTHER,
    OtherWorkflowRefusedError,
    choose_other_workflow,
    choose_repository,
    choose_run_location,
    held_request_text,
    repository_missing,
    workspace_missing,
)
from ...services.workflow_routing.proposal_approval import decide_workflow_proposal_approval
from ...services.workflow_routing.proposal_decision import (
    RESULT_ALREADY_DECIDED,
    RESULT_INVALID,
    RESULT_NOT_FOUND,
    RESULT_NOT_PENDING,
    pending_workflow_proposal,
)
from .._helpers._chat_state_builder import _build_chat_state
from .._helpers.api_guards import _require_api_user
from .._helpers.chat_turn_ack_state import _build_chat_turn_ack_state

router = APIRouter()


class WorkflowProposalDecisionRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=64)
    # Allow once / Always for this Workspace / Deny (continue without the workflow) / Other workflow (with
    # ``workflow_key``: the card shows that workflow instead, nothing is decided yet).
    decision: Literal["apply", "always", "skip", "other"]
    workflow_key: str | None = Field(default=None, max_length=180)
    # A phased start's run location: one of the card's ``start.run_on.options`` keys (default: the card's default).
    run_on: str | None = Field(default=None, max_length=500)
    # A phased start's repository: one of the card's ``start.repository.options`` (its id or its reference).
    repository: str | None = Field(default=None, max_length=500)
    # A phased start's model for a device location (e.g. claude-sonnet-5-5, gpt-6.1-sol); empty: the device default.
    model: str | None = Field(default=None, max_length=200)
    # A phased start's run budget for its Work item (e.g. {"cost_usd": 15}); its stories inherit it.
    budget: dict | None = None


@router.get("/chat/api/turn-traces/{trace_id}/execution-summary")
async def chat_turn_execution_summary_api(
    request: Request,
    trace_id: str,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    summary = await load_user_turn_execution_summary(db, user_id=user.id, trace_id=trace_id)
    if summary is None:
        # Same non-disclosing response as the turn-trace route for unknown and foreign traces.
        raise HTTPException(status_code=404, detail="Turn trace not found")
    return JSONResponse(summary)


async def _prepare_answer(db: AsyncSession, *, session_id: str, user_id: str,
                          payload: WorkflowProposalDecisionRequest) -> None:
    # A phased start without its Workspace or repository is refused (409) before anything is decided.
    from sqlalchemy import select

    session = (await db.execute(select(AgentSession).where(
        AgentSession.id == session_id, AgentSession.user_id == user_id))).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    pending = pending_workflow_proposal(session.metadata_)
    if pending is None or pending.get("proposal_id") != payload.proposal_id:
        if payload.decision == ANSWER_OTHER or payload.run_on or payload.repository or payload.budget:
            raise HTTPException(status_code=409, detail="This workflow proposal is no longer pending")
        return  # a plain answer: the decision path says whether it is already decided
    if payload.decision == ANSWER_OTHER:
        try:
            await choose_other_workflow(db, session=session, workflow_key=payload.workflow_key or "",
                                        message=await held_request_text(db, session))
        except OtherWorkflowRefusedError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    else:
        if payload.model and not payload.run_on:
            raise HTTPException(status_code=422, detail="Choose one of your devices under Run on to pick a model.")
        if payload.budget:
            from ...services.workflow_routing.phased_start import choose_budget
            from ...services.workflow_runs.limits import validate_run_limits

            try:
                checked = validate_run_limits({"budget": payload.budget}).get("budget") or {}
            except ValueError as error:
                raise HTTPException(status_code=422, detail=f"Invalid budget: {error}") from error
            choose_budget(session, checked)
        if payload.run_on:
            choose_run_location(session, payload.run_on, model=payload.model or "")
            if payload.model:
                await _check_card_model(db, session, user_id=user_id, run_on=payload.run_on, model=payload.model)
        if payload.repository and not choose_repository(session, payload.repository):
            raise HTTPException(status_code=422, detail="Choose one of the repositories the card offers.")
        if payload.decision != "skip" and workspace_missing(session):
            from ...services.run_admission.denials import workspace_required_detail

            raise HTTPException(status_code=409, detail=workspace_required_detail())
        missing = repository_missing(session) if payload.decision != "skip" else None
        if missing:
            # The card says it before: a run without its repository never starts.
            raise HTTPException(status_code=409, detail=missing)
    await db.commit()


async def _check_card_model(db, session, *, user_id: str, run_on: str, model: str) -> None:
    # A card model only for a device location and only one the device may run there; refused before anything starts.
    from ...models import User
    from ...services.devices.device_models import admitted_device_model
    from ...services.workflow_routing.phased_start import chosen_start
    from ...services.workflow_runs.runtime_target.target import target_options

    user = await db.get(User, user_id)
    target = next((option["target"] for option in await target_options(db, user=user) if option["key"] == run_on),
                  None) if user is not None else None
    if not target or target.get("kind") != "device":
        raise HTTPException(status_code=422, detail="Choose one of your devices under Run on to pick a model.")
    _model, refused = await admitted_device_model(
        db, user_id=user_id, workspace_id=str(chosen_start(session).get("project_id") or ""),
        profile=str(target.get("profile") or ""), device_id=str(target.get("device_id") or ""), model=model)
    if refused is not None:
        raise HTTPException(status_code=422, detail=f"This model is not allowed here ({refused[1]}).")


@router.post("/chat/api/sessions/{session_id}/workflow-proposal")
async def chat_workflow_proposal_decision_api(
    request: Request,
    session_id: str,
    payload: WorkflowProposalDecisionRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Answer the pending workflow proposal by deciding its one approval record; idempotent."""
    user = await _require_api_user(request, db)
    if payload.decision != "skip":
        await _prepare_answer(db, session_id=session_id, user_id=user.id, payload=payload)
        if payload.decision == ANSWER_OTHER:
            return JSONResponse(await _build_chat_state(request, db, user=user, session_id=session_id))
    session_factory = getattr(request.app.state, "async_session_factory", async_session_factory)
    result = await decide_workflow_proposal_approval(
        db,
        session_id=session_id,
        user_id=user.id,
        proposal_id=payload.proposal_id,
        answer=payload.decision,
        session_factory=session_factory,
    )
    if result.outcome == RESULT_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Session not found")
    if result.outcome == RESULT_INVALID:
        raise HTTPException(status_code=400, detail="Unknown workflow proposal decision")
    if result.outcome == RESULT_NOT_PENDING:
        raise HTTPException(status_code=409, detail="This workflow proposal is no longer pending")
    if result.outcome == RESULT_ALREADY_DECIDED:
        state = await _build_chat_state(request, db, user=user, session_id=session_id)
        return JSONResponse({**state, "workflowProposalDecision": RESULT_ALREADY_DECIDED})
    session = await db.get(AgentSession, session_id)
    await db.refresh(session)
    metadata = dict(session.metadata_ or {})
    state = await _build_chat_turn_ack_state(
        request,
        db,
        user=user,
        session=session,
        runtime_target_id=str(metadata.get("runtime_target_id") or ""),
        thinking_level=str(metadata.get("thinking_level") or "light"),
        agent_id=str(metadata.get("agent_definition_id") or ""),
        agent_type=session.agent_type or DEFAULT_AGENT_MODE_KEY,
    )
    return JSONResponse({**state, "workflowProposalDecision": result.decision})
