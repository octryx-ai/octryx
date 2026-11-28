"""Workflow runs over MCP for an octryx-claude session. A run starts only once the user confirmed it."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..models import User, WorkflowRun
from .mcp_governed_knowledge import CHAT_TRANSPORT, McpCaller
from .mcp_workflow_run_chat import _chat_follow, _chat_without_run
from .mcp_workflow_run_session import _NO_LAUNCHER, _contract, _gateway, _refusal, _view
from .workflow_runs.octryx.attach import (
    active_run_of_item,
    session_runtime_target,
    start_confirmed_run,
    take_over,
    work_item_in_workspace,
)
from .workflow_runs.records import WorkflowRunError, active_run_for_session

DOR_TOOL = "submit_definition_of_ready"


async def mcp_workflow_run_select(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    from .workflow_runs.engine import published_phased_flow

    key = str(arguments.get("workflow_key") or "").strip()[:180]
    run_id = str(arguments.get("run_id") or "").strip()[:36]
    phased = await published_phased_flow(db, key, workspace_id) if key else None
    reference = str(arguments.get("work_item") or "").strip()
    if not (run_id or reference or phased):
        return None
    if phased is not None and not run_id:
        from .devices.device_turn_results import caller_device_job
        from .workflow_runs.records import active_run_for_session

        job = await caller_device_job(db, caller, user, workspace_id)
        if job is not None and await active_run_for_session(db, job.session_id) is None:
            # A chat thread's agent proposes; the chat shows the composer's start card and the person confirms.
            from .workflow_routing.agent_start_card import chat_start_card

            return await chat_start_card(db, job=job, user=user, workflow_key=key, reference=reference)
    gateway = await _gateway(db, caller, user, workspace_id)
    if gateway is None:
        return dict(_NO_LAUNCHER)
    if caller.chat_session_id:
        return await _chat_follow(db, chat=gateway, user=user, workspace_id=workspace_id, run_id=run_id,
                                  reference=reference)
    try:
        if run_id:
            run = await take_over(db, gateway_session=gateway, user=user, workspace_id=workspace_id,
                                  run=await db.get(WorkflowRun, run_id))
            return {"state": "selected", "workflow_run": await _contract(db, run, user, gateway)}
        reference = reference or str(dict(gateway.metadata_ or {}).get("work_item_key") or "")
        item = await work_item_in_workspace(db, reference, workspace_id)
        if item is None:
            return {"state": "needs_clarification", "reason": "work_item_unknown",
                    "message": "Name a Work item of this Workspace (work_item) or a run (run_id)."}
        existing = await active_run_of_item(db, item)
        if existing is not None:
            run = await take_over(db, gateway_session=gateway, user=user, workspace_id=workspace_id, run=existing)
            return {"state": "selected", "workflow_run": await _contract(db, run, user, gateway)}
        if phased is None:
            return {"state": "needs_clarification", "reason": "phased_workflow_required",
                    "message": "The Work item has no active run; name the phased workflow to start."}
        return await _start(db, caller=caller, user=user, workspace_id=workspace_id, key=key, item=item,
                            gateway=gateway, repository=arguments.get("repository"),
                            runtime=arguments.get("runtime_target") or arguments.get("runtime"))
    except WorkflowRunError as error:
        return _refusal(error)


async def _start(db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, key: str, item: Any,
                 gateway: Any, repository: Any, runtime: Any = None) -> dict[str, Any]:
    # An agent never starts a run alone: the user confirms it first.
    from .agent_gateway.confirmation import CONFIRMATION_ACTION_PREFIX
    from .approval.request_service import ensure_approval_request
    from .mcp_workflow_confirmation import _confirmation_answer, _confirmation_session, _latest_confirmation

    session = await _confirmation_session(db, caller=caller, user=user, workspace_id=workspace_id,
                                          workflow_key=key, create=True)
    metadata = dict(session.metadata_ or {})
    if metadata.get("work_item_id") != item.id:
        session.metadata_ = {**metadata, "work_item_id": item.id}
        flag_modified(session, "metadata_")
    approval = await _latest_confirmation(db, session, key)
    if approval is not None and approval.status == "approved":
        target = await session_runtime_target(db, gateway_session=gateway, grant_id=caller.grant_id,
                                              requested=runtime)
        run = await start_confirmed_run(db, gateway_session=gateway, user=user, workspace_id=workspace_id,
                                        workflow_key=key, item=item, repository=str(repository or "") or None,
                                        runtime_target=target)
        return {"state": "selected", "approval_id": approval.id,
                "workflow_run": await _contract(db, run, user, gateway)}
    if approval is not None and approval.status == "rejected":
        return {"state": "denied", "reason": "confirmation_rejected", "approval_id": approval.id}
    if approval is None:
        approval = await ensure_approval_request(
            db, requested_by=user.id, action=CONFIRMATION_ACTION_PREFIX + key, session_id=session.id,
            reason=f"An octryx-claude session asks to start the workflow run '{key}' for {item.source_key}.")
    return _confirmation_answer(approval, session, {"workflow_key": key, "work_item": item.source_key,
                                                    "execution_kind": "phased"})


async def mcp_workflow_run_status(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    from .workflow_runs.access import run_access

    run_id = str(arguments.get("run_id") or "").strip()[:36]
    gateway = await _gateway(db, caller, user, workspace_id)
    if run_id:
        run = await db.get(WorkflowRun, run_id)
        if run is None or run.project_id != workspace_id or await run_access(db, run, user) == "none":
            # Gemma passed the workflow key as the run id. A session that follows a run gets that
            # run's contract (the same answer as without an id), with a note; any other session stays not_found.
            bound = await active_run_for_session(db, gateway.id) if gateway is not None else None
            if bound is None:
                return {"state": "not_found", "reason": "unknown_run"}
            return {"state": "ok", "note": f"No run {run_id!r}; this session follows run {bound.id}, its contract "
                                           "is below. Call workflow_run_status without arguments.",
                    "workflow_run": _view(await _contract(db, bound, user, gateway), arguments)}
    else:
        if gateway is None:
            # A chat is never told to start octryx-claude: it has no run here (see ``_chat_without_run``).
            return (await _chat_without_run(db, user=user, workspace_id=workspace_id) if caller.chat_session_id
                    else dict(_NO_LAUNCHER))
        run = await active_run_for_session(db, gateway.id)
        if run is None:
            if caller.chat_session_id:
                return await _chat_without_run(db, user=user, workspace_id=workspace_id)
            return {"state": "not_found", "reason": "no_run_bound",
                    "message": "This session follows no workflow run (workflow_select with a run or Work item)."}
    return {"state": "ok", "workflow_run": _view(await _contract(db, run, user, gateway), arguments)}


async def mcp_workflow_action_request(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    from .workflow_runs.access import run_access
    from .workflow_runs.octryx.actions import request_action

    gateway = await _gateway(db, caller, user, workspace_id)
    if gateway is None:
        return dict(_NO_LAUNCHER)
    run = await active_run_for_session(db, gateway.id)
    if run is None:
        return {"state": "not_found", "reason": "no_run_bound"}
    if run.project_id != workspace_id or await run_access(db, run, user) != "write":
        # Checked again at every action: access revoked after the session attached ends its actions.
        return {"state": "denied", "reason": "run_access_revoked",
                "message": "You may no longer act on this workflow run."}
    return await request_action(db, run, action=str(arguments.get("action") or ""), params=arguments.get("params"),
                                principal=user, session=gateway)


async def _submit_phase_output(
    db: AsyncSession, tool: str, *, caller: McpCaller, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    from .workflow_runs.access import run_access
    from .workflow_runs.phase_outputs import submit_output
    from .workflow_runs.records import lock_run

    gateway = await _gateway(db, caller, user, workspace_id)
    if gateway is None:
        return dict(_NO_LAUNCHER)
    run = await active_run_for_session(db, gateway.id)
    if run is None:
        return {"state": "not_found", "reason": "no_run_bound"}
    if run.project_id != workspace_id or await run_access(db, run, user) != "write":
        return {"state": "denied", "reason": "run_access_revoked", "message": "You may no longer act on this run."}
    phase = (await _contract(db, run, user, gateway)).get("phase") if run.status == "running" else None
    tools = dict((phase or {}).get("tools") or {})
    if tool not in (tools.get("allow") or []) or tool in (tools.get("deny") or []):
        return {"state": "denied", "reason": "outside_phase_tools",
                "message": f"The run's current phase does not offer {tool}."}
    try:
        run = await lock_run(db, run)
    except WorkflowRunError as error:
        return _refusal(error)
    answer = await submit_output(db, run, tool, arguments, principal=user, session_id=gateway.id)
    if answer["state"] != "recorded":
        return {**answer, "state": "denied" if answer.get("reason") == "outside_phase_output" else "invalid_request"}
    return answer


def _phase_output_handler(tool: str):
    async def handler(db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str,
                      arguments: dict[str, Any]) -> dict[str, Any]:
        return await _submit_phase_output(db, tool, caller=caller, user=user, workspace_id=workspace_id,
                                          arguments=arguments)

    handler.__name__ = f"mcp_{tool}"
    return handler


mcp_submit_definition_of_ready = _phase_output_handler(DOR_TOOL)
# Every phase output tool (``workflow_runs/phase_outputs``): run-bound, only while the current phase offers it.
PHASE_OUTPUT_MCP_HANDLERS = {tool: _phase_output_handler(tool) for tool in (
    "submit_test_contract", "submit_reproduction", "submit_incident_hypothesis", "submit_feature_documentation",
    "submit_phase_result", "submit_work_plan", "submit_story_plan", "submit_spec_studio", "submit_change_plan")}
PHASE_OUTPUT_MCP_HANDLERS[DOR_TOOL] = mcp_submit_definition_of_ready


async def mcp_workflow_decide(
    db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    # Only with the ticket of the user's accepted permission prompt.
    from .agent_gateway.decision_confirmation import redeem_decision_ticket
    from .workflow_runs.access import run_access
    from .workflow_runs.octryx.decisions import arguments_digest, decide_in_terminal

    run_id = str(arguments.get("run_id") or "").strip()[:36]
    action, hash_value = str(arguments.get("action") or "").strip()[:40], str(arguments.get("payload_hash") or "")
    chat = caller.transport == CHAT_TRANSPORT and bool(caller.chat_session_id)
    if caller.transport != "mcp" and not chat:
        return {"state": "denied", "reason": "mcp_channel_required"}
    gateway = await _gateway(db, caller, user, workspace_id)
    if gateway is None:
        return dict(_NO_LAUNCHER)
    run = await active_run_for_session(db, gateway.id)
    if run is None or run.id != run_id:
        return {"state": "not_found", "reason": "no_run_bound"}
    if run.project_id != workspace_id or await run_access(db, run, user) != "write":
        return {"state": "denied", "reason": "run_access_revoked", "message": "You may no longer act on this run."}
    ticket = {"run_id": run.id, "action": action, "payload_hash": hash_value,
              "arguments_digest": arguments_digest(arguments), "ticket": arguments.get("confirmation_ticket"),
              "tool_use_id": caller.tool_use_id}
    # In a chat the person confirmed exactly this call (tool, run, action and payload) before it ran.
    if not chat and not await redeem_decision_ticket(db, session=gateway, **ticket):
        # Never on the user's behalf: no accepted permission prompt, no decision.
        return {"state": "needs_confirmation", "reason": "confirm_in_permission_prompt",
                "message": "Only the user decides: in Claude Code's permission prompt or in Octryx.",
                "decide_in": (await _contract(db, run, user, gateway)).get("link")}
    savepoint = await db.begin_nested()  # the accepted prompt stays used up, whatever the decision's outcome
    try:
        run = await decide_in_terminal(db, run, user=user, action=action, hash_value=hash_value, arguments=arguments)
    except WorkflowRunError as error:
        # As in the run card: a refreshed payload stays (persist), anything else of a refused decision is undone.
        await (savepoint.commit() if error.persist else savepoint.rollback())
        return _refusal(error)
    await savepoint.commit()
    return {"state": "decided", "action": action, "workflow_run": await _contract(db, run, user, gateway)}


__all__ = [
    "PHASE_OUTPUT_MCP_HANDLERS",
    "mcp_submit_definition_of_ready",
    "mcp_workflow_action_request",
    "mcp_workflow_decide",
    "mcp_workflow_run_select",
    "mcp_workflow_run_status",
]
