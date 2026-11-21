"""Gate-blocked turns are runs with the gate's outcome, not successful model runs.

A turn that the execution gate or the runtime-readiness gate blocks never reaches a
model. In Observability → Runs it has the gate's outcome (``blocked``, or ``needs_clarification``
when the gate asks for it) and exactly one ``gate`` step, with no model step. The run carries the
gate's explicit outcome and its frozen execution profile (effective setup), and records no
provider construction, usage event or tokens. Only the explicit marker a gate writes decides;
a provider name or ``source`` string alone never makes a run ``blocked``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
import app.agent.providers as providers_module
from app.agent.core.runtime.trace_runtime import persist_turn_trace
from app.agent.engine import run_agent
from app.models import ControlPlaneRuntimeTarget, LLMProvider, TurnTrace, UsageEvent, User
from app.models import Session as AgentSession
from app.services.control_plane_service import upsert_runtime_target
from app.services.observability.run_detail import get_run_detail
from app.services.observability.runs_read_model import list_runs
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests.observability_support import run_summary
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


class _ProviderGuard:
    def __init__(self) -> None:
        self.constructions = 0

    def factory(self, **_kwargs):
        self.constructions += 1
        raise AssertionError("a gate-blocked turn must not build a provider")


@pytest.fixture
def provider_guard(monkeypatch) -> _ProviderGuard:
    guard = _ProviderGuard()
    monkeypatch.setattr(providers_module, "get_provider", guard.factory)
    monkeypatch.setattr(engine_module, "get_provider", guard.factory)
    return guard


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _session(db, *, metadata: dict) -> AgentSession:
    admin = await _admin(db)
    session = AgentSession(id=str(uuid.uuid4()), user_id=admin.id, agent_type="chat", metadata_={**UNDECLARED_READ_ONLY_RUN, **metadata})
    db.add(session)
    await db.commit()
    return session


async def _run_turn(db, session: AgentSession, message: str, *, runtime_target_id: str | None = None) -> list:
    admin = await _admin(db)
    events = [
        event
        async for event in run_agent(
            session_id=session.id,
            user_message=message,
            user_id=admin.id,
            project_id=None,
            agent_type="chat",
            db=db,
            runtime_target_id=runtime_target_id,
        )
    ]
    await db.commit()
    return events


async def _blocked_detail(db, session: AgentSession, *, gate: str, label: str, decision_status: str, outcome: str) -> dict:
    trace = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalar_one()
    detail = await get_run_detail(db, (await run_summary(db, trace.id)).run_key)
    assert detail["outcome"] == outcome
    assert [(step["kind"], step["gate"]["gate"], step["gate"]["label"], step["gate"]["status"]) for step in detail["steps"]] == [
        ("gate", gate, label, decision_status)
    ]
    # Nothing was attempted, billed, or counted.
    assert [(step["tokens_in"], step["tokens_out"]) for step in detail["steps"]] == [(0, 0)]
    assert detail["cost"]["by_model"] == []
    usage = (await db.execute(select(UsageEvent).where(UsageEvent.session_id == session.id))).scalars().all()
    assert usage == []
    return detail


@pytest.mark.asyncio
async def test_readiness_blocked_turn_is_a_blocked_gate_run_without_attempt_or_usage(db, provider_guard):
    for target in (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().all():
        await db.delete(target)
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="bedrock",
        driver="bedrock_api",
        display_name=f"Bedrock {uuid.uuid4().hex[:6]}",
        auth_mode="aws_credentials",
        aws_region="eu-central-1",
        default_model_id="amazon.nova-2-lite-v1:0",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    target = await upsert_runtime_target(
        db, provider=provider, model_id="amazon.nova-2-lite-v1:0", make_primary=True, is_active=True
    )
    session = await _session(db, metadata={})

    events = await _run_turn(db, session, "Reply with exactly SHOULD-NOT-RUN.", runtime_target_id=target.id)

    assert "requires configuration" in events[-1].content
    detail = await _blocked_detail(
        db, session, gate="runtime_readiness", label="runtime readiness gate", decision_status="needs_configuration",
        outcome="blocked",
    )
    assert detail["effective_setup"]["status"] == "allowed"
    assert detail["effective_setup"]["runtime"]["runtime_target_id"] == target.id
    assert provider_guard.constructions == 0
    blocked = await list_runs(db, outcome="blocked")
    assert [item["run_key"] for item in blocked["items"]] == [detail["run_key"]]
    assert (await list_runs(db, outcome="failed"))["total"] == 0


@pytest.mark.asyncio
async def test_execution_gate_blocked_turn_records_the_gate_outcome_and_the_frozen_profile(db, provider_guard):
    # An unknown explicit workflow_key resolves to needs_clarification; the execution
    # gate blocks the run before any runtime or provider is touched.
    session = await _session(
        db,
        metadata={
            ROUTING_RESOLUTION_KEY: {
                "source": "explicit_workflow_key",
                "status": "unknown_key",
                "workflow_key": "no-such-workflow",
                "unmatched_reason": "Unknown workflow_key 'no-such-workflow'.",
            }
        },
    )

    events = await _run_turn(db, session, "Run the no-such-workflow flow.")

    assert events and events[-1].content
    detail = await _blocked_detail(
        db, session, gate="execution_gate", label="execution gate", decision_status="needs_clarification",
        outcome="needs_clarification",
    )
    profile = detail["effective_setup"]
    assert profile["status"] == "needs_clarification"
    assert profile["decision_source"] == "explicit_workflow_key"
    assert profile["profile_id"] == "needs_clarification:explicit_workflow_key"
    assert provider_guard.constructions == 0


@pytest.mark.asyncio
async def test_blocked_status_needs_the_explicit_gate_marker(db):
    """A gate provider name or ``source`` payload alone never makes a run blocked."""
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
