"""The mechanisms a size class switches on, shown on synthetic workflows with their own names.

- ``skip_nodes``: the check is left out and the run takes its succeeded exit, with ``node_skipped`` naming the class;
- ``session: "shared"``: the next phase resumes the run's session (not one session per phase);
- ``context_cap_tokens``: past the cap the pass starts fresh with a handoff note (no unbounded context per call);
- ``agent_note``: the class's note reaches the agent's contract;
- a launcher restart retries the pass once in its session (generic, not a pause for a person).
Nothing here names a shipped workflow, step or class.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import UsageEvent, WorkflowRun, WorkflowRunEvent
from app.services.devices.job_events import apply_event
from app.services.devices.job_offer import offer_body
from app.services.workflow_runs.records import start_run
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased, run_workspace
from tests.workflow_run_octryx_continuation_support import (  # noqa: F401
    TWO_PHASES,
    _confirm,
    _device_run,
    _hub,
    _jobs,
    _reenter,
)


def _classes(settings: dict) -> dict:
    return {"default": "pick", "rules": [], "classes": {"pick": settings, "other": {}}}


@pytest.mark.asyncio
async def test_a_skipped_check_takes_its_succeeded_exit_and_says_why(db):
    definition = {
        "execution_kind": "phased",
        "nodes": [{"id": "go", "type": "start"},
                  {"id": "look", "type": "platform_action", "config": {"action": "hands_on.run"}},
                  {"id": "make", "type": "phase", "label": "Make", "config": copy.deepcopy(PHASE)},
                  {"id": "fine", "type": "outcome", "config": {"outcome": "done"}},
                  {"id": "nope", "type": "outcome", "config": {"outcome": "blocked"}}],
        "edges": [{"id": "e1", "source_node_id": "go", "target_node_id": "look"},
                  {"id": "e2", "source_node_id": "look", "target_node_id": "make", "when": "succeeded"},
                  {"id": "e3", "source_node_id": "look", "target_node_id": "nope", "when": "failed"},
                  {"id": "e4", "source_node_id": "make", "target_node_id": "fine"}],
        "size_classes": _classes({"skip_nodes": [{"node": "look"}]}),
    }
    workspace_id = await run_workspace(db, await admin_user(db))
    run = await start_run(db, user=await admin_user(db), workflow_key=await publish_phased(db, definition),
                          project_id=workspace_id)
    assert (run.status, run.current_node_id) == ("running", "make")
    [skipped] = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "node_skipped"))).scalars()
    assert (skipped.node_id, skipped.detail["class"]) == ("look", "pick")


async def _next_phase(db, settings: dict | None, *, context_tokens: int = 0):
    definition = {**copy.deepcopy(TWO_PHASES), **({"size_classes": _classes(settings)} if settings else {})}
    admin, _device, thread, run = await _device_run(db, definition=definition)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_event", {"kind": "session", "claude_session_id": "claude-run-1"}, limits={})
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    if context_tokens:
        db.add(UsageEvent(session_id=thread.id, user_id=admin.id, model="m", tokens_in=10, tokens_out=900,
                          cache_read_tokens=context_tokens - 10, cache_creation_tokens=0,
                          dispatch_owner="model_gateway_inbound_anthropic_seat"))
        await db.flush()
    await _reenter(db, run, "more")
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert job.status == "offered"
    return run, job


@pytest.mark.asyncio
async def test_a_shared_session_class_resumes_the_runs_session_at_the_next_phase(db):
    _run, job = await _next_phase(db, {"session": "shared"})
    assert offer_body(job, limits={})["resume_session_id"] == "claude-run-1"
    assert "next phase in this session: phase 'More'" in job.turn_prompt and "do not re-read" in job.turn_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [None, {"session": "per_phase"}, {}])
async def test_without_a_shared_session_each_phase_starts_fresh_as_before(db, settings):
    _run, job = await _next_phase(db, settings)
    assert offer_body(job, limits={})["resume_session_id"] is None


@pytest.mark.asyncio
async def test_past_the_classes_context_cap_another_engine_starts_fresh_with_a_handoff_once(db, monkeypatch):
    """An engine without auto-compaction (the session to resume is not Claude Code's) starts fresh past the cap."""
    from app.services.workflow_runs.octryx import compaction
    from app.services.workflow_runs.run_texts import run_text

    async def other_engine(_db, _session):
        return False

    monkeypatch.setattr(compaction, "compacts_itself", other_engine)
    handoff = run_text("context_cap.handoff")
    run, job = await _next_phase(db, {"session": "shared", "context_cap_tokens": 50_000}, context_tokens=60_000)
    assert offer_body(job, limits={})["resume_session_id"] is None and job.turn_prompt.startswith(handoff)
    [capped] = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "session_context_capped"))).scalars()
    assert (capped.detail["context_tokens"], capped.detail["cap"]) == (60_000, 50_000)
    _run, below = await _next_phase(db, {"session": "shared", "context_cap_tokens": 50_000}, context_tokens=40_000)
    assert offer_body(below, limits={})["resume_session_id"] == "claude-run-1"


@pytest.mark.asyncio
async def test_past_the_classes_context_cap_a_claude_code_session_goes_on_and_compacts_at_the_cap(db):
    """Claude Code compacts itself: its session is resumed past the cap, no handoff, and the
    offer carries the class's cap as the window it compacts at (``octryx.compaction``)."""
    from app.services.devices.jobs_channel import _thread_run
    from app.services.workflow_runs.run_texts import run_text

    run, job = await _next_phase(db, {"session": "shared", "context_cap_tokens": 150_000}, context_tokens=160_000)
    assert offer_body(job, limits={})["resume_session_id"] == "claude-run-1"
    assert not job.turn_prompt.startswith(run_text("context_cap.handoff"))
    assert (await _thread_run(db, job)).get("compact_window") == 150_000


def test_the_classes_note_reaches_the_agents_contract():
    from app.services.workflow_runs.size_class.steps import agent_facts

    run = WorkflowRun(context={"size_class": {"class": "pick", "classes": {"pick": {"agent_note": "Stay small."}}}})
    assert agent_facts(run) == {"class": "pick", "note": "Stay small."}
    assert agent_facts(WorkflowRun(context={})) is None


@pytest.mark.asyncio
async def test_a_launcher_restart_retries_the_pass_once_in_the_same_session(db):
    from datetime import timedelta

    from app.services.workflow_runs.runtime_target.device_wait import resume_for_device
    from app.time_utils import utc_now

    admin, device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    job.claude_session_id = "claude-run-1"
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "failed",
                                                 "reason": "service_restarted"}, limits={})
    assert (run.status, run.waiting_kind) == ("waiting", "waiting_for_device")
    waiting = run.node_state["waiting"]
    run.node_state = {**run.node_state, "waiting": {**waiting, "retry_after": (
        utc_now() - timedelta(seconds=1)).isoformat()}}
    assert await resume_for_device(db, device.id) == [run.id]
    assert job.turn_count == 2 and offer_body(job, limits={})["resume_session_id"] == "claude-run-1"


def test_a_red_hands_on_pass_resumes_with_its_delta_not_the_whole_contract(monkeypatch):
    from app.services.workflow_runs.graph import PhasedNode
    from app.services.workflow_runs.octryx import continuation_prompts

    red = {"scenario": "S1", "failed_step": "16: expect_text", "reason": "'15.0' is not shown"}
    monkeypatch.setattr(continuation_prompts, "_phase_facts", lambda _run, _node: {"hands_on_failure": red})
    prompt = continuation_prompts._resumed_prompt(WorkflowRun(id="r1"), PhasedNode(id="x", kind="phase", title="X",
                                                                           config={}), retry=False)
    assert "hands-on test of the built app failed" in prompt and "'15.0' is not shown" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "confirms"), [("reproduce", True), (None, False)])
async def test_a_skipped_reproduce_check_still_confirms_the_reproduction_the_next_gate_judges(
        monkeypatch, mode, confirms):
    """A skipped reproduce check must still confirm the submitted reproduction, else the gate after it finds no
    confirmed test, loops and the run pauses."""
    from app.services.workflow_runs.graph import PhasedNode
    from app.services.workflow_runs.hands_on import reproduce
    from app.services.workflow_runs.size_class import steps

    calls = []

    async def confirm(_db, run):
        calls.append(run.id)

    monkeypatch.setattr(reproduce, "confirm_automatically", confirm)
    monkeypatch.setattr(steps, "record_event", lambda *_args, **_kwargs: None)
    node = PhasedNode(id="look", kind="platform_action", title="Look",
                      config={"action": "hands_on.run", **({"mode": mode} if mode else {})})
    run = WorkflowRun(id="r1", context={"size_class": {"class": "pick", "skips": ["look"]}})
    assert await steps.skip_entered(None, run, node) is True
    assert calls == (["r1"] if confirms else [])


async def _passed_into_next_phase(db, settings: dict):
    definition = {**copy.deepcopy(TWO_PHASES), "size_classes": _classes(settings)}
    admin, _device, thread, run = await _device_run(db, definition=definition)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await _reenter(db, run, "more")  # the Stop that passed the first phase moved the run on, its turn still runs
    return run, job


def _ended_unfinished_once(run) -> None:
    """The pass already ended unfinished once: the second time (stall_after, default 2) pauses (the
    first time it goes on by itself, tests/test_platform_evidence.py)."""
    from app.services.workflow_runs.octryx.same_pass import UNFINISHED_KEY

    run.context = {**dict(run.context or {}), UNFINISHED_KEY: {
        "node_id": run.current_node_id, "entry": dict(run.node_state or {}).get("entry"), "times": 1}}


@pytest.mark.asyncio
async def test_a_same_turn_class_goes_on_with_the_next_phase_in_the_running_turn(db):
    """Ending the turn at each phase change of a small item and starting the same session again costs 20-30 s.
    With ``phase_change: same_turn`` the passing Stop hands the agent the next phase's prompt and the
    running turn becomes that phase's pass: when it ends unfinished the run pauses, no new turn starts."""
    from app.services.workflow_runs.octryx.continuation_marker import CONTEXT_KEY
    from app.services.workflow_runs.octryx.same_turn import CAPABILITY, continue_in_turn

    run, job = await _passed_into_next_phase(db, {"session": "shared", "phase_change": "same_turn"})
    prompt = await continue_in_turn(db, run, {"capabilities": [CAPABILITY]})
    assert "next phase in this session: phase 'More'" in prompt
    marker = run.context[CONTEXT_KEY]
    assert (marker["state"], marker["job_id"], marker["node_id"]) == ("started", job.id, "more")
    _ended_unfinished_once(run)
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert (run.status, run.pause_reason) == ("paused", "phase_not_finished")
    assert job.status != "offered"  # no second turn for the phase the running turn already did


@pytest.mark.asyncio
@pytest.mark.parametrize(("settings", "capabilities"), [
    ({"session": "shared", "phase_change": "new_turn"}, ["next_phase"]),
    # Without phase_change a shared class changes inside the turn (see tests/test_session_keep.py).
    ({"session": "per_phase"}, ["next_phase"]),
    ({"session": "shared", "phase_change": "same_turn"}, []),  # a launcher without the phase change: the turn ends
])
async def test_otherwise_the_phase_change_ends_the_turn_and_the_next_one_starts_as_before(db, settings, capabilities):
    from app.services.workflow_runs.octryx.same_turn import continue_in_turn

    run, job = await _passed_into_next_phase(db, settings)
    assert await continue_in_turn(db, run, {"capabilities": capabilities}) == ""
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert run.status == "running" and job.status == "offered" and "phase 'More'" in job.turn_prompt
