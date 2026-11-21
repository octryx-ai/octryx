"""Server phases: a phase's model maps to the active runtime target serving it, a refused or missing one keeps the thread's runtime, and the server guard matrix."""

# ruff: noqa: F811  (the shared ``seat_admitted`` fixture is imported, then requested by name)
from __future__ import annotations

import copy

import pytest

from app.services.session.turn_refusals import TurnRefusal, TurnRefusalState
from app.services.workflow_runs import server_continuation as sc
from app.services.workflow_runs.runtime_target.server_build import build_steps, server_build_refusal
from tests.phase_seat_models_support import HAIKU  # noqa: F401 - fixture
from tests.phase_sessions_models_support import _events, _server_run, _target, _with_phase
from tests.phased_workflow_fixtures import PHASE
from tests.test_workflow_run_server_continuation import _Shared, sent  # noqa: F401 - fixture
from tests.workflow_run_octryx_continuation_support import (  # noqa: F401 - autouse fixture: a clean device hub
    DEFINITION,
    _hub,
)

# --- the server guard -----------------------------------------------------------------------------------------------

def _team_like(*, pipeline: bool = True, checks: list[dict] | None = None) -> dict:
    """A building phase that allowlists ``run_test_suite``, optionally with checks, and optionally a pipeline."""
    phase = copy.deepcopy(PHASE)
    phase["tool_policy"]["allowlist"] = [*phase["tool_policy"]["allowlist"], "run_test_suite"]
    phase["workflow_contract"]["checks"] = checks or []
    nodes = [{"id": "start", "type": "start"}, {"id": "backend", "type": "phase", "label": "Backend", "config": phase}]
    if pipeline:
        nodes.append({"id": "pipeline", "type": "platform_action", "label": "CI pipeline",
                      "config": {"action": "pipeline.run"}})
    return {"execution_kind": "phased", "nodes": nodes, "edges": []}


_SUITE_CALLED = {"type": "tool_called", "params": {"tools": ["run_test_suite"]}, "description": "The suite ran"}


@pytest.mark.asyncio
async def test_a_phase_model_maps_to_the_active_runtime_target_serving_it(db):
    inactive = await _target(db, HAIKU, active=False, priority=1)
    bedrock = await _target(db, f"anthropic.{HAIKU}", priority=60)
    assert await sc.phase_runtime_target_id(db, HAIKU) == bedrock.id  # the inactive exact one never answers
    exact = await _target(db, HAIKU, priority=70)
    assert await sc.phase_runtime_target_id(db, HAIKU) == exact.id  # the exact id before a provider prefix
    assert inactive.id != exact.id
    assert await sc.phase_runtime_target_id(db, "claude-sonnet-9") is None
    assert await sc.phase_runtime_target_id(db, "") is None


@pytest.mark.asyncio
async def test_a_server_phase_turn_runs_on_its_models_runtime_target(db, sent):  # noqa: F811
    calls, _answer = sent
    haiku = await _target(db, HAIKU)
    thread, _run = await _server_run(db, _with_phase(DEFINITION, "work", model=HAIKU))
    await sc.start_pending_turn(thread.id, session_factory=_Shared(db))
    assert [call["runtime_target_id"] for call in calls] == [haiku.id]


@pytest.mark.asyncio
async def test_a_server_phase_without_a_serving_target_keeps_the_threads_runtime(db, sent):  # noqa: F811
    calls, _answer = sent
    thread, _run = await _server_run(db, _with_phase(DEFINITION, "work", model="claude-sonnet-9"))
    await sc.start_pending_turn(thread.id, session_factory=_Shared(db))
    assert [call["runtime_target_id"] for call in calls] == [None]


@pytest.mark.asyncio
async def test_a_refused_phase_runtime_falls_back_to_the_threads_runtime_visibly(db, monkeypatch):
    calls: list[dict] = []

    async def refuse_explicit(db_, **kwargs):
        calls.append(kwargs)
        if kwargs.get("runtime_target_id"):
            return TurnRefusal(state=TurnRefusalState.RUNTIME_NOT_ALLOWED, detail="not in this Workspace")
        return []

    monkeypatch.setattr("app.services.session.message_dispatch.send_session_message", refuse_explicit)
    monkeypatch.setattr(sc, "schedule_continuation", lambda *a, **k: None)
    haiku = await _target(db, HAIKU)
    thread, run = await _server_run(db, _with_phase(DEFINITION, "work", model=HAIKU))
    await sc.start_pending_turn(thread.id, session_factory=_Shared(db))
    assert [call["runtime_target_id"] for call in calls] == [haiku.id, None]
    assert run.status == "running"
    [event] = await _events(db, run, sc.EVENT_MODEL_REFUSED)
    assert event.detail == {"runtime_target_id": haiku.id, "reason": "runtime_not_allowed"}


@pytest.mark.parametrize(("definition", "steps"), [
    (_team_like(), []),  # the pipeline judges the tests; the allowlist only permits a run
    (_team_like(pipeline=False), ["Backend"]),  # nothing else judges them: refused
    (_team_like(checks=[{"type": "test_command_passed", "params": {}, "blocking": True}]), ["Backend"]),
    (_team_like(checks=[{"type": "test_command_passed", "params": {}}]), ["Backend"]),  # blocking by default
    (_team_like(checks=[{**_SUITE_CALLED, "blocking": True}]), ["Backend"]),
    (_team_like(checks=[{**_SUITE_CALLED, "blocking": False}]), []),  # advisory
    (_team_like(pipeline=False, checks=[{**_SUITE_CALLED, "blocking": False}]), ["Backend"]),
])
def test_the_server_guard_matrix(definition, steps):
    assert build_steps(definition) == steps
    refusal = server_build_refusal({"kind": "server"}, definition=definition)
    assert (refusal[1] if refusal else []) == steps
    assert server_build_refusal({"kind": "device", "device_id": "d"}, definition=definition) is None
