"""Turn traces record the run's execution profile.

Every turn trace records the execution profile its run was prepared with. Run preparation
freezes a bounded, redacted projection on the run context
(``ToolContext.execution_profile_trace``). The turn's context snapshot carries it into the
turn trace, and Observability → Runs shows it as the run's effective setup. Trace persistence never
re-reads the session row, because another turn of the same session may have rewritten it in between.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
import app.agent.providers as providers_module
from app.agent.core.runtime.trace_runtime import gate_trace_context_snapshot, persist_turn_trace
from app.agent.engine import run_agent
from app.models import ControlPlaneRuntimeTarget, LLMProvider, TurnTrace, User
from app.models import Session as AgentSession
from app.services.control_plane_service import upsert_runtime_target
from app.services.execution_profile_service import build_execution_profile
from app.services.execution_profile_trace import execution_profile_trace_summary
from app.services.observability.run_detail import get_run_detail
from app.services.trace_events import REDACTED_VALUE
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.tools.context import ToolContext
from tests.observability_support import run_summary
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


def _profile(*, workflow_key: str | None, target_id: str) -> dict:
    resolution = (
        {"source": "workflow_routing_policy", "status": "unmatched"}
        if workflow_key is None
        else {
            "source": "db",
            "status": "matched",
            "selection_source": "workflow_run",
            "policy_id": f"policy-{workflow_key}",
            "policy_version_id": f"version-{workflow_key}",
            "workflow_id": "coding_change_tdd",
            "workflow_class": "coding_change",
        }
    )
    return build_execution_profile(
        prompt="Say hello.",
        requested_agent_type="chat",
        effective_agent_type="chat",
        execution_strategy="direct" if workflow_key is None else "coordinator",
        execution_strategy_reason="strategy:direct_default",
        routing_intent="diagnosis",
        routing_reason="intent:diagnosis_default",
        routing_intent_confidence=1.0,
        routing_intent_source="default",
        workflow_id="" if workflow_key is None else "coding_change_tdd",
        workflow_contract={} if workflow_key is None else {"workflow_id": "coding_change_tdd"},
        workflow_routing_policy_resolution=resolution,
        runtime_target_id=target_id,
        runtime_label=f"Bedrock / {target_id}",
    ).to_metadata()


PROFILE_A = _profile(workflow_key=None, target_id="target-a")
PROFILE_B = _profile(workflow_key="b", target_id="target-b")


def _run_context(session_id: str, profile: dict | None) -> ToolContext:
    return ToolContext(
        user_id="user",
        project_ids=[],
        roles=[],
        session_id=session_id,
        project_config={},
        execution_profile_trace=execution_profile_trace_summary(profile),
    )


async def _session(db, *, profile: dict | None, project_id: str | None = None) -> AgentSession:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = AgentSession(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project_id,
        agent_type="chat",
        metadata_={**UNDECLARED_READ_ONLY_RUN, **({"execution_profile": profile} if profile else {})},
    )
    db.add(session)
    await db.flush()
    return session


async def _persist(db, session: AgentSession, context_snapshot: dict) -> tuple[TurnTrace, dict]:
    await persist_turn_trace(
        db=db,
        session_id=session.id,
        message_id=None,
        provider="bedrock",
        model="amazon.nova-2-lite-v1:0",
        input_messages=[{"role": "user", "content": "Say hello."}],
        context_snapshot=context_snapshot,
        tool_trace=[],
        raw_output={
            "content": "Hello.",
            "runtime_attempts": [
                {"provider": "bedrock", "model": "amazon.nova-2-lite-v1:0", "target_id": "target-a", "status": "success"}
            ],
        },
        usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    )
    await db.commit()
    trace = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalar_one()
    return trace, await get_run_detail(db, (await run_summary(db, trace.id)).run_key)


@pytest.mark.asyncio
async def test_trace_keeps_the_frozen_run_profile_when_the_session_row_is_rewritten(db):
    session = await _session(db, profile=PROFILE_A)
    run_context = _run_context(session.id, PROFILE_A)
    # Another turn of the same session rewrites the row before turn A persists its trace.
    session.metadata_ = {**session.metadata_, "execution_profile": PROFILE_B}
    await db.flush()

    trace, run = await _persist(db, session, {**gate_trace_context_snapshot(run_context), "request_id": "req-a"})

    legacy_profile = trace.context_snapshot_json["execution_profile"]
    assert legacy_profile["decision_source"] == "direct_chat_safe"
    assert legacy_profile["runtime"]["runtime_target_id"] == "target-a"
    assert run["effective_setup"] == legacy_profile
    assert "policy-b" not in json.dumps(run)
    assert session.metadata_["execution_profile"]["decision_source"] == "workflow_run"


@pytest.mark.asyncio
async def test_full_turn_trace_keeps_profile_a_while_an_overlapping_turn_rewrites_the_session(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = await _session(db, profile=None)
    # As both entry paths record it before the run: this turn's (unmatched) selection.
    session.metadata_ = {
        ROUTING_RESOLUTION_KEY: {"source": "workflow_routing_policy", "status": "unmatched"}
    }
    await db.commit()
    rewrites: list[str] = []

    def _factory(**_kwargs):
        class _Client:
            async def chat(self, messages, model=None, **_ignored):
                # Mid-turn, another turn of this session commits profile B to the row.
                row = await db.get(AgentSession, session.id)
                row.metadata_ = {**(row.metadata_ or {}), "execution_profile": PROFILE_B}
                await db.flush()
                rewrites.append(row.id)
                return {"content": "PONG-A", "tool_calls": None, "model": model or "", "usage": {}}

            async def close(self):
                return None

        return _Client()

    monkeypatch.setattr(providers_module, "get_provider", _factory)
    monkeypatch.setattr(engine_module, "get_provider", _factory)

    async for _event in run_agent(
        session_id=session.id,
        user_message="Say hello in one short sentence.",
        user_id=admin.id,
        project_id=None,
        agent_type="chat",
        db=db,
    ):
        pass
    await db.commit()

    assert rewrites == [session.id]
    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().all()
    assert len(traces) == 1
    run = await get_run_detail(db, (await run_summary(db, traces[0].id)).run_key)
    recorded = run["effective_setup"]
    assert recorded["decision_source"] == "direct_chat_safe"
    assert recorded["profile_id"] == "direct_chat_safe"
    assert recorded["policy"]["status"] == "unmatched"
    assert traces[0].context_snapshot_json["execution_profile"] == recorded
    assert "policy-b" not in json.dumps(run)
    row = await db.get(AgentSession, session.id)
    assert row.metadata_["execution_profile"]["decision_source"] == "workflow_run"


@pytest.mark.asyncio
async def test_frozen_profile_survives_snapshot_truncation(db):
    session = await _session(db, profile=PROFILE_A)
    oversized_snapshot = {f"key_{index:03d}": index for index in range(200)}
    oversized_snapshot.update(gate_trace_context_snapshot(_run_context(session.id, PROFILE_A)))

    trace, run = await _persist(db, session, oversized_snapshot)

    assert "__truncated__" in trace.context_snapshot_json
    assert trace.context_snapshot_json["execution_profile"]["profile_id"] == "direct_chat_safe"
    assert run["effective_setup"]["profile_id"] == "direct_chat_safe"


@pytest.mark.asyncio
async def test_profile_projection_is_redacted_in_the_trace_and_the_run_drawer(client, auth_headers, db):
    leaky = json.loads(json.dumps(PROFILE_A))
    leaky["reason"] = ("operator note api_key=sk-li" + "ve-775-abcdefghijklmnop")
    leaky["runtime"]["runtime_label"] = "Bearer abcdefghijklmnopqrstuvwxyz0123"
    leaky["workflow_contract"] = {"note": "password=hunter2-not-projected"}
    session = await _session(db, profile=leaky)

    trace, _run = await _persist(db, session, gate_trace_context_snapshot(_run_context(session.id, leaky)))
    response = await client.get(
        "/api/v1/observability/runs/detail", params={"run_key": (await run_summary(db, trace.id)).run_key},
        headers=auth_headers
    )

    assert response.status_code == 200
    for projected in (trace.context_snapshot_json["execution_profile"], response.json()["effective_setup"]):
        assert projected["reason"] == REDACTED_VALUE
        assert projected["runtime"]["runtime_label"] == REDACTED_VALUE
        assert "workflow_contract" not in projected
        serialized = json.dumps(projected)
        assert "sk-live-775" not in serialized
        assert "abcdefghijklmnopqrstuvwxyz0123" not in serialized
        assert "hunter2" not in serialized


@pytest.mark.asyncio
async def test_run_without_a_profile_records_none(db):
    session = await _session(db, profile=None)

    trace, run = await _persist(db, session, gate_trace_context_snapshot(_run_context(session.id, None)))

    assert "execution_profile" not in trace.context_snapshot_json
    assert run["effective_setup"] is None


@pytest.mark.asyncio
async def test_readiness_blocked_turn_trace_records_the_profile_it_was_blocked_under(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
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
    session = await _session(db, profile=None)
    await db.commit()

    def _forbidden(**_kwargs):
        raise AssertionError("a readiness-blocked turn must not build a provider")

    monkeypatch.setattr(providers_module, "get_provider", _forbidden)
    monkeypatch.setattr(engine_module, "get_provider", _forbidden)

    events = [
        event
        async for event in run_agent(
            session_id=session.id,
            user_message="Reply with exactly SHOULD-NOT-RUN.",
            user_id=admin.id,
            project_id=None,
            agent_type="chat",
            db=db,
            runtime_target_id=target.id,
        )
    ]
    await db.commit()

    assert "requires configuration" in events[-1].content
    trace = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalar_one()
    run = await get_run_detail(db, (await run_summary(db, trace.id)).run_key)
    assert run["steps"][0]["provider"] == "runtime-readiness-gate"
    recorded = run["effective_setup"]
    assert recorded["status"] == "allowed"
    assert recorded["decision_source"] == "direct_chat_safe"
    assert recorded["runtime"]["runtime_target_id"] == target.id
