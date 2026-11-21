"""Chat turns bound to a Product Run at the execution boundary.

A turn is bound only when its caller passes ``run_origin="chat_turn"``; the run's
states come from explicit gate, readiness, trace and session markers, and every
trace of a bound turn carries the run's identity stamp.
"""

# ruff: noqa: F811  (the shared ``world`` fixture is imported, then requested by name)
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine._engine_product_run import ProductRunUnavailableError
from app.models import ControlPlaneRuntimeTarget, LLMProvider, Project, TurnTrace
from app.models.runtime.product_run import ProductRun
from app.services.control_plane_service import upsert_runtime_target
from app.services.product_run.turn_stamp import read_product_run_stamp
from tests.product_run_chat_binding_support import (
    FINAL_RESPONSE,
    OPENED,
    TOOL_RESPONSE,
    TRANSIENT,
    _attempt,
    _audit,
    _drain,
    _session,
    _turn,
)
from tests.product_run_chat_support import TOOL, world  # noqa: F401 - fixture


async def _stamps(db, session_id: str) -> list:
    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session_id))).scalars().all()
    assert traces, "the turn persisted no trace"
    return [read_product_run_stamp(trace.context_snapshot_json) for trace in traces]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("project_config", "script", "end"),
    [
        ({}, [TOOL_RESPONSE, FINAL_RESPONSE], ("finished_unverified", "runtime_finished")),
        ({}, [TRANSIENT, TRANSIENT], ("failed", "provider_error")),
        ({"approval_policy": {"require_for_tools": [TOOL]}}, [TOOL_RESPONSE], ("waiting_approval", "approval_pending")),
    ],
    ids=["finished", "provider-failure", "approval-pending"],
)
async def test_an_admitted_chat_turn_ends_in_the_state_its_markers_imply(
    db, monkeypatch, world, project_config, script, end
) -> None:
    world.update(project_config=project_config, script=list(script))
    session = await _session(db)

    await _drain(_turn(db, session))

    assert world["script"] == []
    attempt = await _attempt(db, session.id)
    assert (attempt.state, attempt.end_reason) == end
    assert (attempt.gate_status, attempt.gate_decision_source) == ("allowed", "execution_profile")
    assert await _audit(db, attempt.run_id) == [*OPENED, ("running", *end)]
    run = await db.get(ProductRun, attempt.run_id)
    assert (run.workspace_id, run.owner_user_id, run.origin) == (session.project_id, session.user_id, "chat_turn")
    # Every trace of the turn, including those persisted before the terminal move, names the stored run.
    stamps = await _stamps(db, session.id)
    assert {(s.status, s.run_id, s.attempt_id, s.attempt_number, s.origin) for s in stamps} == {
        ("bound", run.id, attempt.id, attempt.attempt_number, run.origin)
    }


@pytest.mark.asyncio
async def test_a_gate_block_ends_the_run_before_admission_without_a_model_call(db, monkeypatch, world) -> None:
    real_prepare = engine_module._prepare_agent_run

    async def prepare_needing_configuration(**kwargs):
        prepared = await real_prepare(**kwargs)
        profile = dict(prepared.session_metadata.get("execution_profile") or {})
        prepared.session_metadata["execution_profile"] = {**profile, "status": "needs_configuration"}
        return prepared

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare_needing_configuration)
    world["script"] = [AssertionError("a gate-blocked turn must not call the model")]
    session = await _session(db)

    events = await _drain(_turn(db, session))

    assert "requires configuration" in events[-1].content
    assert world["calls"] == 0
    attempt = await _attempt(db, session.id)
    assert (attempt.state, attempt.end_reason, attempt.gate_status) == (
        "needs_configuration",
        "gate_needs_configuration",
        "needs_configuration",
    )
    assert await _audit(db, attempt.run_id) == [
        (None, "requested", None),
        ("requested", "needs_configuration", "gate_needs_configuration"),
    ]
    assert {(s.status, s.attempt_id) for s in await _stamps(db, session.id)} == {("bound", attempt.id)}


@pytest.mark.asyncio
async def test_a_readiness_block_ends_an_admitted_run_in_needs_configuration(db, world) -> None:
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
    session = await _session(db)

    events = await _drain(_turn(db, session, runtime_target_id=target.id))

    assert "requires configuration" in events[-1].content
    assert world["calls"] == 0
    attempt = await _attempt(db, session.id)
    assert await _audit(db, attempt.run_id) == [
        (None, "requested", None),
        ("requested", "admitted", None),
        ("admitted", "needs_configuration", "runtime_not_ready"),
    ]
    assert attempt.gate_status == "allowed"


@pytest.mark.asyncio
async def test_closing_the_turn_stream_cancels_the_run(db, world) -> None:
    world["script"] = [FINAL_RESPONSE]
    session = await _session(db)
    events = _turn(db, session)

    await events.__anext__()
    await events.aclose()

    attempt = await _attempt(db, session.id)
    assert (attempt.state, attempt.end_reason) == ("cancelled", "generator_closed")
    assert (await _audit(db, attempt.run_id))[-1] == ("running", "cancelled", "generator_closed")


@pytest.mark.asyncio
async def test_cancelling_the_turn_task_cancels_the_run(db, world) -> None:
    model_called = asyncio.Event()

    async def never_answers():
        model_called.set()
        await asyncio.Event().wait()

    world["script"] = [never_answers]
    session = await _session(db)
    session_id = session.id
    task = asyncio.create_task(_drain(_turn(db, session)))
    await asyncio.wait_for(model_called.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The cancelled turn's uncommitted work was rolled back, which expires loaded objects.
    attempt = await _attempt(db, session_id)
    assert (attempt.state, attempt.end_reason) == ("cancelled", "task_cancelled")


@pytest.mark.asyncio
async def test_a_session_without_a_workspace_opens_no_run_and_is_stamped_unscoped(db, world) -> None:
    world["script"] = [FINAL_RESPONSE]
    session = await _session(db, with_workspace=False)

    await _drain(_turn(db, session))

    assert (await db.execute(select(ProductRun).where(ProductRun.session_id == session.id))).first() is None
    assert {(s.status, s.origin, s.run_id) for s in await _stamps(db, session.id)} == {("unscoped", "chat_turn", None)}


@pytest.mark.asyncio
async def test_a_caller_without_run_origin_stays_unbound(db, world) -> None:
    world["script"] = [FINAL_RESPONSE]
    session = await _session(db)

    await _drain(_turn(db, session, run_origin=None))

    assert (await db.execute(select(ProductRun).where(ProductRun.session_id == session.id))).first() is None
    assert {s.status for s in await _stamps(db, session.id)} == {"missing"}


@pytest.mark.asyncio
async def test_a_run_that_cannot_be_opened_fails_the_turn_closed(db, world) -> None:
    # A project id that is not a canonical Workspace UUID cannot scope a run.
    project = Project(id="legacy-project-1", name=f"legacy-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = await _session(db, project_id=project.id)
    session_id = session.id

    with pytest.raises(ProductRunUnavailableError) as raised:
        await _drain(_turn(db, session))

    assert raised.value.code == "product_run_unavailable"
    assert world["calls"] == 0
    assert (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session_id))).first() is None
