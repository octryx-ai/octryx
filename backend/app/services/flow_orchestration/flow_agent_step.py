"""Run a workflow ``agent_step`` through the real agent runtime.

The node runs the selected agent, or fails explicitly:

1. reference (``flow_agent_reference.py``): exists for the acting user, active, in scope;
2. resolution: ``resolve_agent_definition_for_execution`` decides which content runs (published
   revision or the saved definition in draft mode) and records its provenance; a definition the platform
   will not execute fails the node instead of running without its agent;
3. execution: a child session of the flow run (same workspace, the flow run's declared capability
   class, ``parent_session_id`` = the flow session) runs one turn through ``agent.engine.run_agent``
   with ``run_origin=sub_agent`` — the same governed runtime the scheduler and sub-agents use
   (execution gate, tool policy, providers, approvals); no second agent loop;
4. outcome: the child turn's final trace read through ``turn_execution_summary.v1`` (the closed
   states the chat UI shows). Only ``finished_unverified``/``completed`` is node success; every
   other state raises :class:`FlowAgentStepError` with a closed code, so downstream nodes never
   receive fabricated output. ``config.mock_output`` is never used.
5. output: ``result`` is the final text as returned; ``data`` is added only when the agent's checked
   JSON reply was satisfied, parsed from that exact text; free text is never coerced.

An ``agent_step`` without an agent but with a ``prompt`` runs the workflow's default agent type
through the same runtime (provenance ``no_agent_definition``); a policy-only step and a
``supervisor`` node have no executable contract here and fail as unsupported.
The child turn itself (running, outcome, terminal state) lives in ``flow_agent_turn.py``.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_execution_states import STATUS_INACTIVE, STATUS_NEEDS_PUBLICATION, STATUS_NOT_FOUND

from ...models import OrchestratorAgentRun, Session
from ..agent_definition_execution import resolve_agent_definition_for_execution
from ..agent_definition_execution_outcomes import payload_resolution_metadata
from ..flow_runtime_governance import FlowRuntimeLimitExceededError, FlowRuntimeLimits, FlowRuntimeUsage
from ..orchestrator_service import add_child_session
from ..run_capability.declared import DECLARED_RUN_CAPABILITY_METADATA_KEY
from ..runtime_failure_errors import ClassifiedFlowError
from .flow_agent_reference import (
    AGENT_INACTIVE,
    AGENT_NOT_ACCESSIBLE,
    FlowAgentReferenceError,
    check_flow_agent_reference,
)
from .flow_agent_turn import (
    _OUTCOMES,
    _UNKNOWN_OUTCOME,
    SUCCESS_STATES,
    _checked_reply_data,
    _finish_child,
    _provenance,
    _reload_expired,
    _remaining_seconds,
    _run_agent_turn,
    _turn_facts,
    _turn_state,
)
from .run_capability import flow_run_capability

AgentTurnRunner = Callable[..., Awaitable[str]]
MAX_INPUT_CHARS = 12000


class FlowAgentStepError(ClassifiedFlowError):
    """An agent node that did not produce an accepted agent result."""


def _configuration_error(code: str) -> FlowAgentStepError:
    return FlowAgentStepError(code, category="input_contract_error", required_action="fix_workflow_configuration")


def agent_task(prompt: str, input_snapshot: dict[str, Any]) -> str:
    """The user message of the child turn: the step's instructions and its complete input as JSON.

    The input is never cut: an input above ``MAX_INPUT_CHARS`` fails the node before any model call
    (``agent_step_input_too_large``) instead of running the agent on silently dropped data.
    """
    instructions = prompt.strip() or "Complete this workflow step using the input below."
    rendered = json.dumps(input_snapshot, ensure_ascii=False, indent=2, default=str)
    if len(rendered) > MAX_INPUT_CHARS:
        raise _configuration_error("agent_step_input_too_large")
    return f"{instructions}\n\nWorkflow step input (JSON):\n{rendered}"


async def _resolve(db: AsyncSession, agent_id: str, user_id: str) -> dict[str, Any]:
    resolution = await resolve_agent_definition_for_execution(db, definition_id=agent_id, visible_to_user_id=user_id)
    if resolution.resolved:
        return dict(resolution.payload or {})
    if resolution.status == STATUS_NOT_FOUND:
        raise FlowAgentReferenceError(AGENT_NOT_ACCESSIBLE)
    if resolution.status == STATUS_INACTIVE:
        # Same typed result as the reference guard before the node runs.
        raise FlowAgentReferenceError(AGENT_INACTIVE)
    if resolution.status == STATUS_NEEDS_PUBLICATION:
        raise _configuration_error("agent_needs_publication")
    raise _configuration_error("agent_execution_not_configured")


async def execute_flow_agent_step(
    db: AsyncSession,
    *,
    orchestrator_run: OrchestratorAgentRun,
    node_id: str,
    node_type: str,
    config: dict[str, Any],
    input_snapshot: dict[str, Any],
    user_id: str,
    agent_type: str,
    limits: FlowRuntimeLimits | None = None,
    usage: FlowRuntimeUsage | None = None,
    run_turn: AgentTurnRunner | None = None,
) -> dict[str, Any]:
    """Run the node's agent for one turn; return its accepted result or raise a closed failure."""
    agent_id, prompt, payload = await _step_agent(
        db, orchestrator_run, node_type=node_type, config=config, user_id=user_id
    )
    task = agent_task(prompt, input_snapshot)  # refuses oversized input before any session or model call
    effective_type = str((payload or {}).get("agentType") or "") or agent_type
    child = await _open_child_session(
        db, orchestrator_run, node_id=node_id, node_type=node_type, agent_id=agent_id, payload=payload,
        user_id=user_id, effective_type=effective_type,
    )
    runner = run_turn or _run_agent_turn
    remaining = _remaining_seconds(limits, usage)
    # Read before the turn: a turn that ends abnormally may roll the shared session back, which
    # expires every loaded object; synchronous attribute loads would then fail.
    version_id = orchestrator_run.flow_definition_version_id
    flow_session_id = orchestrator_run.session_id
    child_id = child.id
    try:
        final_text = await _await_turn(
            db, child, runner, task=task, payload=payload, user_id=user_id, agent_type=effective_type,
            flow_session_id=flow_session_id, node_id=node_id, version_id=version_id, remaining=remaining,
            limits=limits,
        )
        summary, trace = await _turn_state(db, child_id)
        facts = _turn_facts(summary, trace)
        if facts["state"] not in SUCCESS_STATES:
            code, category, action = _OUTCOMES.get(facts["state"], _UNKNOWN_OUTCOME)
            raise FlowAgentStepError(code, category=category, required_action=action)
    except BaseException as exc:
        # Every failure, timeout or cancellation leaves the child terminal, never "active".
        reason = getattr(exc, "code", None) or "agent_turn_failed"
        try:
            await _finish_child(db, child, succeeded=False, reason=str(reason))
        except Exception:  # noqa: BLE001 - recording the child's end must not mask the node failure
            pass
        raise
    await _finish_child(db, child, succeeded=True, reason="flow_agent_step_completed")
    output = {"result": final_text, "session_id": child_id, "agent": _provenance(agent_id, payload), "turn": facts}
    data = _checked_reply_data(summary, final_text)
    if data is not None:
        output["data"] = data
    return output


async def _step_agent(
    db: AsyncSession, orchestrator_run: OrchestratorAgentRun, *, node_type: str, config: dict[str, Any], user_id: str
) -> tuple[str, str, dict[str, Any] | None]:
    """The step's agent id, prompt and resolved agent payload; refuses a step that cannot run an agent."""
    if node_type == "supervisor":
        raise _configuration_error("supervisor_execution_unsupported")
    agent_id = str(config.get("agent_definition_id") or "").strip()
    prompt = str(config.get("prompt") or "")
    payload: dict[str, Any] | None = None
    if agent_id:
        await check_flow_agent_reference(
            db, definition_id=agent_id, user_id=user_id, flow_project_id=orchestrator_run.project_id
        )
        payload = await _resolve(db, agent_id, user_id)
    elif not prompt.strip():
        raise _configuration_error("agent_step_needs_agent")
    return agent_id, prompt, payload


async def _open_child_session(
    db: AsyncSession,
    orchestrator_run: OrchestratorAgentRun,
    *,
    node_id: str,
    node_type: str,
    agent_id: str,
    payload: dict[str, Any] | None,
    user_id: str,
    effective_type: str,
) -> Session:
    capability = await flow_run_capability(db, orchestrator_run)
    child = Session(
        id=str(uuid.uuid4()),
        user_id=user_id,
        project_id=orchestrator_run.project_id,
        agent_type=effective_type,
        status="active",
        origin="flow",
        parent_session_id=orchestrator_run.session_id,
        # ``flow_definition_version_id``/``flow_node_id`` are set only after the turn: during it,
        # ``run_agent`` would treat a session carrying them as a flow session and start the workflow again.
        metadata_={
            "flow_node_id": node_id,
            "flow_node_type": node_type,
            "flow_run_id": orchestrator_run.id,
            "flow_version_id": orchestrator_run.flow_definition_version_id,
            "flow_agent_definition_id": agent_id or None,
            DECLARED_RUN_CAPABILITY_METADATA_KEY: capability.to_metadata(),
            **payload_resolution_metadata(payload),
        },
    )
    db.add(child)
    await db.flush()
    await add_child_session(db, orchestrator_run, child.id)
    return child


async def _await_turn(
    db: AsyncSession,
    child: Session,
    runner: AgentTurnRunner,
    *,
    task: str,
    payload: dict[str, Any] | None,
    user_id: str,
    agent_type: str,
    flow_session_id: str | None,
    node_id: str,
    version_id: str | None,
    remaining: float | None,
    limits: FlowRuntimeLimits | None,
) -> str:
    """The child turn's final text; any turn failure becomes one closed node failure."""
    try:
        turn = runner(
            db=db,
            session=child,
            task=task,
            payload=payload,
            user_id=user_id,
            agent_type=agent_type,
            parent_session_id=flow_session_id,
        )
        # The turn is awaited inside the node, so the run cannot complete while it runs; past the flow's
        # max_run_seconds it is cancelled and the node fails with the run-timeout limit.
        return await (turn if remaining is None else asyncio.wait_for(turn, timeout=remaining))
    except TimeoutError as exc:
        raise FlowRuntimeLimitExceededError(
            "flow_run_timeout_exceeded",
            f"Flow run exceeded configured max_run_seconds={limits.max_run_seconds if limits else None}.",
            {"max_run_seconds": limits.max_run_seconds if limits else None, "node_id": node_id},
        ) from exc
    except (ClassifiedFlowError, FlowRuntimeLimitExceededError):
        raise
    except Exception as exc:  # noqa: BLE001 - the runtime's own errors become one closed node failure
        raise FlowAgentStepError("agent_turn_failed", category="runtime_exception") from exc
    finally:
        await _reload_expired(db)
        child.flow_definition_version_id = version_id
        child.flow_node_id = node_id
        await db.flush()


__all__ = ["FlowAgentStepError", "agent_task", "execute_flow_agent_step"]
