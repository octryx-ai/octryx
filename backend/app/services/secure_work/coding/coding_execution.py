from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    Session,
    User,
    WorkChangePlan,
    WorkItem,
    WorkItemChangeUnit,
)
from ...prompt_catalog import prompt_set_scope
from ...prompt_catalog.out_of_turn import prompt_set_for
from ...session.turn_refusals import TurnRefusal
from ...session.turn_request import TurnRequest
from ...workflow_routing.platform_selection import SECURE_WORK_CODING_EXECUTION
from ..jira_values import blank_to_none, string_list
from ..lifecycle_transitions import STATE_DEVELOPMENT, auto_transition_work_item
from .coding_pipelines import start_coding_pipeline_run
from .coding_workspaces import (
    attach_workspace_session,
    prepare_coding_workspaces,
    workspace_metadata_patch,
)
from .execution_pipeline_summary import (
    _mark_pipeline_agent_session_started,
    _persist_pipeline_context_budget,
    _persist_pipeline_workspace_summary,
    _with_context_budget_summary,
    _with_workspace_summary,
)
from .execution_prompt import _agent_execution_prompt, _build_agent_context_budget
from .execution_scope import _approved_plan, _get_work_item, _selected_units
from .execution_start_records import (
    ExecutionStart,
    _blocked_execution,
    _record_execution_start,
    _started_result,
)

StartChatTurn = Callable[..., Awaitable[Session]]


async def start_work_item_coding_agent_execution(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
    start_chat_turn_func: StartChatTurn | None = None,
) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    plan = await _approved_plan(db, item, blank_to_none(payload.get("change_plan_id")))
    if plan is None:
        raise HTTPException(status_code=409, detail="Approved Work Plan required before agent execution can start")
    units = await _selected_units(db, item, payload.get("change_unit_ids"))
    pipeline_run = await _start_pipeline(
        db, item=item, plan=plan, units=units, payload=payload, current_user=current_user
    )
    blockers = list(((pipeline_run.get("summary") or {}).get("execution_context") or {}).get("blockers") or [])
    if pipeline_run.get("status") == "policy_blocked":
        return _blocked_execution(db, item, plan, pipeline_run, blockers, current_user)

    restart_from_scratch = bool(payload.get("restart_from_scratch"))
    restart_reason = str(payload.get("restart_reason") or "").strip()
    workspaces, pipeline_run, context_budget, prompt_set = await _prepare_execution(
        db, item=item, plan=plan, units=units, pipeline_run=pipeline_run, payload=payload,
        current_user=current_user, restart_from_scratch=restart_from_scratch,
    )

    # Chat turn preparation uses an isolated DB session so the agent can run
    # independently from the request lifecycle. Commit the pipeline preflight
    # first; otherwise local SQLite holds a writer lock and the chat session
    # cannot be created reliably.
    await db.commit()

    with prompt_set_scope(prompt_set):
        prompt = _agent_execution_prompt(
            item=item,
            plan=plan,
            units=units,
            pipeline_run=pipeline_run,
            payload=payload,
            workspaces=workspaces,
            context_budget=context_budget,
        )
    session = await _start_execution_session(
        db, starter=start_chat_turn_func or _start_turn_via_owner, item=item, plan=plan, prompt=prompt,
        payload=payload, workspaces=workspaces, current_user=current_user, restart_from_scratch=restart_from_scratch,
    )
    workspaces = await attach_workspace_session(
        db,
        workspace_ids=[str(workspace.get("id") or "") for workspace in workspaces if workspace.get("id")],
        session_id=session.id,
        current_user=current_user,
    )
    started = ExecutionStart(item, plan, units, pipeline_run, session, workspaces, prompt, current_user,
                             restart_from_scratch, restart_reason)
    await _record_execution_start(db, started)
    return await _finish_start(db, started)


async def _finish_start(db: AsyncSession, started: ExecutionStart) -> dict[str, Any]:
    session, current_user = started.session, started.current_user
    refreshed_pipeline_run = await _mark_pipeline_agent_session_started(
        db,
        pipeline_run_id=str(started.pipeline_run.get("id") or ""),
        session_id=session.id,
        current_user=current_user,
    )
    lifecycle_transition = await auto_transition_work_item(
        db,
        item=started.item,
        current_user=current_user,
        to_state=STATE_DEVELOPMENT,
        reason=f"Coding agent execution started (session {session.id}).",
    )
    return _started_result(started, refreshed_pipeline_run or started.pipeline_run, lifecycle_transition)


async def _start_pipeline(
    db: AsyncSession,
    *,
    item: WorkItem,
    plan: WorkChangePlan,
    units: list[WorkItemChangeUnit],
    payload: dict[str, Any],
    current_user: User,
) -> dict[str, Any]:
    return await start_coding_pipeline_run(
        db,
        work_item_id=item.id,
        current_user=current_user,
        payload={
            "config_id": blank_to_none(payload.get("config_id")),
            "change_plan_id": plan.id,
            "change_unit_ids": [unit.id for unit in units],
            "changed_files": string_list(payload.get("changed_files")),
        },
    )

async def _prepare_execution(
    db: AsyncSession,
    *,
    item: WorkItem,
    plan: WorkChangePlan,
    units: list[WorkItemChangeUnit],
    pipeline_run: dict[str, Any],
    payload: dict[str, Any],
    current_user: User,
    restart_from_scratch: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], Any]:
    """Prepare the workspaces and the context budget; returns them with the updated run view and the prompt set."""
    workspaces = await prepare_coding_workspaces(
        db,
        item=item,
        plan=plan,
        units=units,
        pipeline_run_id=str(pipeline_run.get("id") or ""),
        current_user=current_user,
        restart_from_scratch=restart_from_scratch,
    )
    state_machine = await _persist_pipeline_workspace_summary(
        db,
        pipeline_run_id=str(pipeline_run.get("id") or ""),
        workspaces=workspaces,
        current_user=current_user,
    )
    pipeline_run = _with_workspace_summary(pipeline_run, workspaces, state_machine=state_machine)

    prompt_set = await prompt_set_for(db, workspace_id=item.project_id)
    with prompt_set_scope(prompt_set):
        context_budget = _build_agent_context_budget(
            item=item,
            plan=plan,
            payload=payload,
            pipeline_run=pipeline_run,
        )
    await _persist_pipeline_context_budget(
        db,
        pipeline_run_id=str(pipeline_run.get("id") or ""),
        context_budget=context_budget,
        current_user=current_user,
    )
    pipeline_run = _with_context_budget_summary(pipeline_run, context_budget)
    return workspaces, pipeline_run, context_budget, prompt_set


async def _start_execution_session(
    db: AsyncSession,
    *,
    starter: StartChatTurn,
    item: WorkItem,
    plan: WorkChangePlan,
    prompt: str,
    payload: dict[str, Any],
    workspaces: list[dict[str, Any]],
    current_user: User,
    restart_from_scratch: bool,
) -> Session:
    # sessions.idempotency_key is VARCHAR(100): the restart key must stay
    # short — item id plus a fresh random suffix is unique enough per restart.
    idempotency_key = (
        f"work-coding-restart:{item.id}:{uuid.uuid4().hex[:12]}"
        if restart_from_scratch
        else f"work-coding-execution:{item.id}:{plan.id}"
    )
    return await starter(
        db=db,
        user=current_user,
        prompt=prompt,
        project_id=item.project_id or "",
        agent_type="coding",
        agent_type_explicit=True,
        # The governed Work Plan run selects its workflow explicitly (coding_change_tdd);
        # routing never infers it from the prompt this service writes.
        platform_workflow_service=SECURE_WORK_CODING_EXECUTION,
        thinking_level=str(payload.get("thinking_level") or "deep"),
        thinking_level_explicit=bool(payload.get("thinking_level")),
        idempotency_key=idempotency_key,
        session_metadata_patch=workspace_metadata_patch(workspaces),
    )


async def _start_turn_via_owner(*, db: AsyncSession, user: User, **request: Any) -> Session:
    """Start the coding turn through the session service owner, with the chat-turn HTTP errors."""
    # Lazy: turn_start reaches the agent engine, which imports the secure-work services.
    from ...session.turn_start import load_prepared_session, start_turn

    started = await start_turn(TurnRequest(user_id=user.id, **request))
    if isinstance(started, TurnRefusal):
        raise HTTPException(status_code=started.http_status, detail=started.detail)
    session = await load_prepared_session(db, started)
    if session is None:
        raise HTTPException(status_code=500, detail="Prepared session could not be reloaded")
    return session
