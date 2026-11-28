"""Gate-blocked turns are runs with the gate's outcome, not successful model runs."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.runtime.trace_runtime import persist_turn_trace
from app.models import Session as AgentSession
from app.models import TurnTrace, User
from app.services.observability.run_detail import get_run_detail
from tests.observability_support import run_summary
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


class _ProviderGuard:
    def __init__(self) -> None:
        self.constructions = 0

    def factory(self, **_kwargs):
        self.constructions += 1
        raise AssertionError("a gate-blocked turn must not build a provider")




async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _session(db, *, metadata: dict) -> AgentSession:
    admin = await _admin(db)
    session = AgentSession(id=str(uuid.uuid4()), user_id=admin.id, agent_type="chat", metadata_={**UNDECLARED_READ_ONLY_RUN, **metadata})
    db.add(session)
    await db.commit()
    return session










@pytest.mark.asyncio
async def test_blocked_status_needs_the_explicit_gate_marker(db):
    session = await _session(db, metadata={})
    common = {
        "db": db,
        "session_id": session.id,
        "message_id": None,
        "input_messages": [],
        "context_snapshot": {},
        "tool_trace": [],
        "usage": {},
    }
    await persist_turn_trace(
        provider="execution-gate",
        model="",
        raw_output={"source": "execution_gate", "profile_status": "needs_clarification", "reason": "legacy"},
        **common,
    )
    await persist_turn_trace(provider="bedrock", model="amazon.nova-2-lite-v1:0", raw_output={"content": "Hi."}, **common)
    await db.commit()

    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().all()
    summaries = [await run_summary(db, trace.id) for trace in traces]
    assert sorted(summary.outcome for summary in summaries) == ["completed", "completed"]
    for summary in summaries:
        detail = await get_run_detail(db, summary.run_key)
        assert [step["kind"] for step in detail["steps"]] == ["model"]
        assert all(step["gate"] is None for step in detail["steps"])
