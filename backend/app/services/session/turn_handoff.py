"""A prepared turn after the execution gate: held for its workflow proposal (the start card waits for the person), or
handed to a runner as the turn of the stored user message."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message
from ...models import Session as AgentSession
from .execution_gate import GATE_SOURCE_WORKFLOW_PROPOSAL, evaluate_execution_gate
from .turn_request import PreparedTurn
from .turn_settlement import settle_turn_after_stream


def names_a_workflow(workflow_key: str | None, workflow_decisions: dict | None) -> bool:
    from ..workflow_routing.proposal_states import WORKFLOW_KEY_NONE

    return bool(workflow_decisions) or str(workflow_key or "").strip() not in ("", WORKFLOW_KEY_NONE)


async def held_by_gate(db: AsyncSession, prepared: PreparedTurn, *, session_factory) -> bool:
    from ..workflow_routing.phased_start import held_turn_message
    from ..workflow_routing.proposal_approval import request_workflow_proposal_approval

    session = await db.get(AgentSession, prepared.session_id)
    await db.refresh(session)
    await _record_capability(db, session, prepared)
    gate = evaluate_execution_gate(dict(session.metadata_ or {}).get("execution_profile"))
    if gate.allowed:  # the prepared turn ends here; the runner's turn is the device job's
        await settle_turn_after_stream(db, session_id=session.id, session_factory=session_factory, request_id=None)
        return False
    message = gate.user_message
    if gate.decision_source == GATE_SOURCE_WORKFLOW_PROPOSAL:
        await request_workflow_proposal_approval(db, session_id=session.id)
        message = held_turn_message(session) or message
    from ...agent.runtime.trace_runtime import persist_turn_trace
    from ...agent.runtime.turn_execution_binding import bind_turn_execution_snapshot
    from .turn_execution_snapshot import build_turn_execution_snapshot

    profile = dict(session.metadata_ or {}).get("execution_profile")
    bind_turn_execution_snapshot(session.id, build_turn_execution_snapshot(
        execution_profile=profile, gate=gate, session_metadata=dict(session.metadata_ or {}),
        agent_definition=prepared.agent_definition))
    answer = Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content=message,
                     model="execution-gate")
    db.add(answer)
    await db.flush()
    # The held turn's trace: its execution summary names what it waits for (``confirm_workflow_proposal``).
    await persist_turn_trace(db=db, session_id=session.id, message_id=answer.id, provider="execution-gate", model="",
                             input_messages=[], context_snapshot={}, tool_trace=[], raw_output=gate.trace_output(),
                             usage={})
    await db.commit()
    await settle_turn_after_stream(db, session_id=session.id, session_factory=session_factory, request_id=None)
    return True


async def _record_capability(db: AsyncSession, session: AgentSession, prepared: PreparedTurn) -> None:
    # The turn's run class (a chat's confirmed connector writes): what the start card's own writes run under.
    from ..run_capability.resolution import resolve_run_capability
    from ..workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

    metadata = dict(session.metadata_ or {})
    resolution = await resolve_run_capability(
        db, session_metadata=metadata, routing_resolution=metadata.get(ROUTING_RESOLUTION_KEY),
        requested_agent_type=prepared.agent_type, agent_definition=prepared.agent_definition,
        parent_session_id=session.parent_session_id)
    profile = dict(metadata.get("execution_profile") or {})
    session.metadata_ = {**metadata, "execution_profile": {**profile, "capability": resolution.to_metadata()}}


async def runner_turn_kwargs(db: AsyncSession, prepared: PreparedTurn) -> dict[str, Any]:
    from ..devices.agent_runtime import chat_target_for

    return {"prompt": prepared.prompt, "session_id": prepared.session_id, "project_id": prepared.project_id or "",
            "target": await chat_target_for(db, prepared.session_id),
            "rerun_message": await db.get(Message, prepared.user_message_id)}


__all__ = ["held_by_gate", "names_a_workflow", "runner_turn_kwargs"]
