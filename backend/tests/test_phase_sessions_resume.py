"""Phase sessions: a loop back resumes each phase's own session, an epic phase resumes the previous story's session on the same device and folder, and team-delivery's plan resumes its own."""

# ruff: noqa: F811  (the shared ``seat_admitted`` fixture is imported, then requested by name)
from __future__ import annotations

import copy

import pytest

from app.services.devices.job_events import apply_event
from app.services.devices.job_offer import offer_body
from app.services.workflow_runs.octryx.phase_sessions import SESSIONS_KEY
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phase_sessions_models_support import _with_phase
from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import PHASE, publish_phased
from tests.workflow_run_octryx_continuation_support import (  # noqa: F401 - autouse fixture: a clean device hub
    DEFINITION,
    FOLDER,
    TWO_PHASES,
    _confirm,
    _device_run,
    _hub,
    _jobs,
    _reenter,
)

# --- one session per phase node -------------------------------------------------------------------------------------

async def _pass(db, job, run, session: str, next_node: str):
    """The device reports the pass's session, the pass's Stop moves the run to ``next_node``, the turn ends."""
    await apply_event(db, job, "job_event", {"kind": "session", "claude_session_id": session}, limits={})
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await _reenter(db, run, next_node)
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})


# --- an epic phase resumes its session of the previous story --------------------------------------------------------

async def _previous_story(db, admin, project_id: str, *, device_id: str, folder: str = FOLDER,
                          profile: str = "governed"):
    """A finished story run of the same epic whose ``work`` phase ran in ``claude-story-1``."""
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, DEFINITION), project_id=project_id,
                          session=await new_chat_session(db, admin, project_id))
    run.context = {**dict(run.context or {}), SESSIONS_KEY: {"work": {
        "node_id": "work", "job_id": None, "turn_id": None, "claude_session_id": "claude-story-1",
        "device_id": device_id, "folder": folder, "profile": profile}}}
    return run


async def _next_story(db, *, epic: bool = True, **previous):
    definition = _with_phase(DEFINITION, "work", session="epic") if epic else DEFINITION
    admin, device, thread, run = await _device_run(db, definition=definition)
    before = await _previous_story(db, admin, run.project_id, **{"device_id": device.id, **previous})
    run.context = {**run.context, "epic_chain": {"epic": "OCX-1", "after_run": before.id,
                                                  "after_workflow": "team-delivery"}}
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    return run, job


# --- the plan after workspace.prepare is the plan's own turn ---------------------------------------------------------

def _seed_node(key: str, node_id: str) -> dict:

    definition = next(seed["definition"] for seed in seed_definitions() if seed["key"] == key)
    return next(node for node in definition["nodes"] if node["id"] == node_id)


def _prepare_then_plan() -> dict:
    """start → go → workspace.prepare → plan (team-delivery's plan model and session) → done."""
    seeded = _seed_node("team-delivery", "plan")["config"]
    # Since G the seed names the class ``plan``; this governed run names its model on the node.
    plan = {**copy.deepcopy(PHASE), "model": "claude-sonnet-5-5", "session": seeded["session"]}
    nodes = [*DEFINITION["nodes"][:2],
             {"id": "prepare", "type": "platform_action", "label": "Prepare",
              "config": {"action": "workspace.prepare"}},
             {"id": "plan", "type": "phase", "label": "Plan", "config": plan},
             *DEFINITION["nodes"][3:]]
    edges = [*DEFINITION["edges"][:1],
             {"id": "e1", "source_node_id": "go", "target_node_id": "prepare", "when": "confirmed"},
             *DEFINITION["edges"][2:4],
             {"id": "e5", "source_node_id": "prepare", "target_node_id": "plan", "when": "succeeded"},
             {"id": "e6", "source_node_id": "prepare", "target_node_id": "blocked", "when": "failed"},
             {"id": "e4", "source_node_id": "plan", "target_node_id": "done"}]
    return {"execution_kind": "phased", "nodes": nodes, "edges": edges}


@pytest.mark.asyncio
async def test_a_loop_back_over_several_phases_resumes_each_phases_own_session(db):
    """Gap 3: with one remembered session a loop from the pipeline back to ``backend`` after ``frontend`` and
    ``tests`` ran started ``backend`` fresh. Each phase node now resumes its own."""
    admin, _device, thread, run = await _device_run(db, definition=TWO_PHASES)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await _pass(db, job, run, "claude-work-1", "more")
    assert offer_body(job, limits={})["resume_session_id"] is None  # a new phase: fresh
    await _pass(db, job, run, "claude-more-1", "work")
    assert offer_body(job, limits={})["resume_session_id"] == "claude-work-1"  # back to work: its own session
    assert "continues in this session" in job.turn_prompt
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await _reenter(db, run, "more")
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert offer_body(job, limits={})["resume_session_id"] == "claude-more-1"
    sessions = run.context[SESSIONS_KEY]
    assert {node: entry["claude_session_id"] for node, entry in sessions.items()} == {
        "work": "claude-work-1", "more": "claude-more-1"}


@pytest.mark.asyncio
async def test_an_epic_phase_resumes_its_session_of_the_previous_story(db):
    run, job = await _next_story(db)
    assert offer_body(job, limits={})["resume_session_id"] == "claude-story-1"
    assert "new story of the same epic" in job.turn_prompt and run.id in job.turn_prompt
    assert "workflow_run_status" in job.turn_prompt  # the new run's contract, read once


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [{"folder": "/home/sample/other"}, {"device_id": "another-device"},
                                      {"profile": "seat"}])
async def test_an_epic_phase_starts_fresh_on_another_device_or_folder(db, previous):
    _run, job = await _next_story(db, **previous)
    assert offer_body(job, limits={})["resume_session_id"] is None
    assert "new story of the same epic" not in job.turn_prompt


@pytest.mark.asyncio
async def test_a_phase_without_the_epic_session_starts_each_story_fresh(db):
    _run, job = await _next_story(db, epic=False)
    assert offer_body(job, limits={})["resume_session_id"] is None


@pytest.mark.asyncio
async def test_team_deliverys_plan_after_prepare_runs_on_sonnet_in_its_own_resumable_session(db, monkeypatch):
    """The plan pass must not run inside the prepare turn on the run's default model, or the replan finds no plan
    session. The prepare turn is the plan's: its model, and its session is the plan's own on the next pass."""
    from app.services.devices import chat_turn

    async def admitted(*_a, **_k):  # the Workspace admits the model (not what this test is about)
        return None

    monkeypatch.setattr(chat_turn, "check_device_model", admitted)
    assert _seed_node("team-delivery", "plan")["config"]["model_class"] == "plan"
    _admin, _device, thread, run = await _device_run(db, definition=_prepare_then_plan())
    run.status, run.waiting_kind = "running", None  # past the start decision
    await _reenter(db, run, "prepare", runtime_step=True)
    [job] = await _jobs(db, thread)
    assert job.turn_model == "claude-sonnet-5-5"
    await apply_event(db, job, "job_event", {"kind": "session", "claude_session_id": "claude-plan-1"}, limits={})
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await _reenter(db, run, "plan")  # the launcher's preparation report: the same turn's agent plans
    assert len(await _jobs(db, thread)) == 1 and job.turn_count == 1  # no second turn for the plan
    run.current_node_id = "work-elsewhere"  # the plan was submitted; the run went on (to the items)
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert run.context[SESSIONS_KEY]["plan"]["claude_session_id"] == "claude-plan-1"
    run.current_node_id = "plan"
    await _reenter(db, run, "plan")  # a replan
    assert offer_body(job, limits={})["resume_session_id"] == "claude-plan-1"
    assert job.turn_model == "claude-sonnet-5-5"
