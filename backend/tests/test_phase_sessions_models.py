"""team-delivery: each role phase runs on its own model and in its own session.

- a phase's explicit ``config.model`` is the device turn's model on the seat too, also over a model chosen on the
  thread; a model the Workspace refuses falls back to the device default with ``run_turn_model_refused``;
- every phase node keeps its own Claude Code session: a loop back over several phases resumes each one's own;
- a phase with ``session: "epic"`` resumes its session of the epic's previous story on the same device and folder,
  else starts fresh;
- on the server a phase's model maps to the active runtime target serving it; none (or a refused one) leaves the
  turn on the thread's runtime;
- a workflow with ``pipeline.run`` and no blocking test checks may start on the server although a phase
  allowlists ``run_test_suite``.
"""

# ruff: noqa: F811  (the shared ``seat_admitted`` fixture is imported, then requested by name)
from __future__ import annotations

import pytest

from app.services.devices.job_events import apply_event, store_event
from app.services.workflow_runs import server_continuation as sc
from tests.phase_seat_models_support import HAIKU, OPUS, seat_admitted  # noqa: F401 - fixture
from tests.phase_sessions_models_support import SONNET, _events, _seat_run, _server_run, _target, _with_phase
from tests.test_workflow_run_server_continuation import _Shared, sent  # noqa: F401 - fixture
from tests.workflow_run_octryx_continuation_support import (  # noqa: F401 - autouse fixture: a clean device hub
    DEFINITION,
    FOLDER,
    _confirm,
    _device_run,
    _hub,
    _jobs,
    _reenter,
)


async def _governed_run_targeting(db, definition: dict, model: str):
    """A governed device run whose stored target (and so its thread) names ``model``."""
    from app.services.workflow_runs.runtime_target.target import stored_target, with_target

    admin, device, thread, run = await _device_run(db, definition=definition)
    target = {"kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed", "model": model}
    run.context = with_target(run.context, target, actor_id=None)
    thread.metadata_ = {**thread.metadata_, "execution_target": {**thread.metadata_["execution_target"],
                                                                 "model": model}}
    assert stored_target(run)["model"] == model
    return admin, thread, run


# --- the pipeline step between two passes keeps the run's target -----------------------------------------------------

SUMMARY_NAMING_A_LIMIT = ("The story is built. Messages I invented: `recipe limit reached: 1000`, "
                          "`too many ingredients: max 100`.")


async def _pass_pipeline_rework(db, run, thread):
    """The phase's turn passes with a summary that names a limit, the pipeline step runs on the device, the review
    asks for changes: the rework pass of the phase is offered. The job of that rework turn."""
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await _reenter(db, run, "work", runtime_step=True)  # the phase passed: the pipeline step
    finished = {"turn_id": job.turn_id, "status": "success", "result_text": SUMMARY_NAMING_A_LIMIT}
    await store_event(db, job, job.last_event_seq + 1, "turn_finished", finished)  # as the job channel does
    await apply_event(db, job, "turn_finished", finished, limits={})
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await _reenter(db, run, "work")  # the independent review asked for changes
    await apply_event(db, job, "job_rejected", {"turn_id": job.turn_id, "reason": "pipeline_done"}, limits={})
    [job] = await _jobs(db, thread)
    return job


@pytest.mark.asyncio
async def test_the_seat_turn_runs_on_the_phase_model_over_the_threads_model(db, seat_admitted):
    """Gap 1 of the design: on the seat the phase model was skipped, so every role ran on the thread's model."""
    admin, thread, run = await _seat_run(db, _with_phase(DEFINITION, "work", model=HAIKU))
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert (job.profile, job.turn_model, job.turn_permission_mode) == ("seat", HAIKU, "acceptEdits")
    assert await _events(db, run, "run_turn_model_refused") == []


@pytest.mark.asyncio
async def test_a_refused_phase_model_falls_back_to_the_device_default_on_the_seat(db, seat_admitted):
    seat_admitted["models"] = {"", OPUS}
    admin, thread, run = await _seat_run(db, _with_phase(DEFINITION, "work", model=HAIKU))
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert (job.profile, job.turn_model or "", job.status) == ("seat", "", "offered")
    [event] = await _events(db, run, "run_turn_model_refused")
    assert event.detail == {"model": HAIKU, "profile": "seat"}


@pytest.mark.asyncio
async def test_without_a_phase_model_the_seat_keeps_the_threads_model(db, seat_admitted):
    admin, thread, run = await _seat_run(db, DEFINITION)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert (job.profile, job.turn_model) == ("seat", OPUS)


def test_the_phase_model_decision_reads_only_the_phases_explicit_model():
    from types import SimpleNamespace

    from app.models import WorkflowRun
    from app.services.workflow_runs.octryx.turn_settings import turn_phase_model
    from app.services.workflow_runs.runtime_target.target import with_target

    def node(**config):
        return SimpleNamespace(kind="phase", config=config)

    targeted = WorkflowRun(context=with_target({}, {"kind": "device", "model": SONNET}, actor_id=None))
    plain = WorkflowRun(context={})
    assert turn_phase_model(targeted, node(model=OPUS)) == OPUS
    assert turn_phase_model(plain, node(model=OPUS)) == OPUS
    assert turn_phase_model(targeted, node()) == ""  # no phase choice: the profile decides
    assert turn_phase_model(targeted, SimpleNamespace(kind="gate", config={"model": HAIKU})) == ""


@pytest.mark.asyncio
async def test_a_server_phase_with_a_model_runs_on_its_runtime_target(db, sent):  # noqa: F811
    calls, _answer = sent
    haiku = await _target(db, HAIKU)
    thread, _run = await _server_run(db, _with_phase(DEFINITION, "work", model=HAIKU))
    await sc.start_pending_turn(thread.id, session_factory=_Shared(db))
    assert [call["runtime_target_id"] for call in calls] == [haiku.id]


@pytest.mark.asyncio
async def test_a_seat_runs_rework_pass_after_the_pipeline_stays_on_the_seat_with_its_model(db, seat_admitted):
    """The CLI message "recipe limit reached: 1000" in an implement summary is not the seat's usage limit: the
    pipeline turn must not move the run to governed, where the rework implement turn fails (403 alias_not_listed).
    Pipeline and rework run on the run's seat target with the phase's model, on the same job."""
    from app.services.workflow_runs.runtime_target.target import stored_target

    admin, thread, run = await _seat_run(db, _with_phase(DEFINITION, "work", model=HAIKU))
    await _confirm(db, run, admin)
    [first] = await _jobs(db, thread)
    rework = await _pass_pipeline_rework(db, run, thread)
    assert rework.id == first.id and rework.status == "offered"
    assert (rework.profile, rework.turn_model) == ("seat", HAIKU)
    assert (stored_target(run) or {}).get("profile", "seat") == "seat"
    assert await _events(db, run, "runtime_profile_governed") == []


@pytest.mark.asyncio
async def test_a_governed_runs_rework_pass_after_the_pipeline_is_unchanged(db, seat_admitted):
    admin, _device, thread, run = await _device_run(db, definition=_with_phase(DEFINITION, "work", model=HAIKU))
    await _confirm(db, run, admin)
    [first] = await _jobs(db, thread)
    rework = await _pass_pipeline_rework(db, run, thread)
    assert rework.id == first.id and rework.status == "offered"
    assert (rework.profile, rework.turn_model) == ("governed", HAIKU)
    assert await _events(db, run, "runtime_profile_governed") == []
