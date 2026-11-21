"""A run's own phase turns: edit mode, phase model, and fresh or resumed device sessions per pass."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import UserDevice
from app.services.devices.job_events import apply_event
from app.services.devices.job_offer import offer_body
from tests.workflow_run_octryx_continuation_support import (  # noqa: F401
    TWO_PHASES,
    _confirm,
    _device_run,
    _hub,
    _jobs,
    _reenter,
)


@pytest.mark.asyncio
async def test_a_runs_own_turn_accepts_edits_unless_the_workspace_asks_before_each_edit(db):
    """A run's 'Tests first' must not wait for a write approval nobody is there to give. The run's own turns
    run in acceptEdits (the platform's hooks still decide every change); a Workspace may ask before each edit."""
    from app.services.agent_gateway.policy import load_workspace_policy

    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert job.turn_permission_mode == "acceptEdits"

    admin2, _d2, thread2, run2 = await _device_run(db)
    from app.services.workflow_runs.octryx.turn_settings import _run_turn_mode

    loaded = await load_workspace_policy(db, run2.project_id)
    raw = dict(loaded.policy.raw)
    raw["device_runs"] = {**dict(raw.get("device_runs") or {}), "run_turns_ask_before_edits": True}
    from app.services.agent_gateway import policy as gateway_policy

    original = gateway_policy.load_workspace_policy

    async def asking(db_, project_id):
        result = await original(db_, project_id)
        result.policy.raw.update(raw) if hasattr(result.policy.raw, "update") else None
        return result

    gateway_policy.load_workspace_policy = asking
    try:
        assert await _run_turn_mode(db, run2) == ""
    finally:
        gateway_policy.load_workspace_policy = original


@pytest.mark.asyncio
async def test_a_runs_own_turn_picks_the_phase_model_and_falls_back_when_not_admitted(db, monkeypatch):
    """A tiny task must not run on the device default's large model. The run's own governed
    turn picks the phase's / Workspace's model; a model the Workspace does not admit falls back to the default."""
    from app.models import WorkflowRunEvent
    from app.services.devices import device_models

    async def admits(*_a, model: str = "", **_k):
        return None if model in ("", "gemma-4-31b") else ("denied", device_models.REASON_MODEL_NOT_ALLOWED)

    monkeypatch.setattr(device_models, "check_device_model", admits)
    from app.services.devices import chat_turn
    monkeypatch.setattr(chat_turn, "check_device_model", admits)

    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    kinds = [e.kind for e in (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id))).scalars()]
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.octryx.turn_settings import _run_turn_model

    node = (await graph_for_run(db, run)).nodes["work"]
    chosen = await _run_turn_model(db, run, node)
    assert chosen == "gemma-4-31b"
    if chosen == "gemma-4-31b":
        assert job.turn_model == "gemma-4-31b"
    else:
        assert "run_turn_model_refused" in kinds and (job.turn_model or "") == ""


@pytest.mark.asyncio
async def test_each_phase_pass_starts_a_fresh_claude_conversation(db):
    """A run's device job must not resume one Claude Code session across all phases, which resends the earlier
    phases' tokens with every call. A phase pass starts fresh (contract + repository are its context); a turn the
    user types still resumes."""
    from app.services.devices.job_offer import offer_body
    from app.services.devices.jobs import start_turn

    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert offer_body(job, limits={})["resume_session_id"] is None  # the phase's own turn
    job.claude_session_id, job.status = "claude-earlier-phase", "idle"
    device = await db.get(UserDevice, job.device_id)
    own = await start_turn(db, owner_user_id=admin.id, device=device, session_id=thread.id,
                           workspace_id=thread.project_id, folder=job.folder, profile=job.profile, prompt="my question")
    assert offer_body(own, limits={})["resume_session_id"] == "claude-earlier-phase"
    own.status = "idle"
    fresh = await start_turn(db, owner_user_id=admin.id, device=device, session_id=thread.id,
                             workspace_id=thread.project_id, folder=job.folder, profile=job.profile,
                             prompt="phase pass", fresh_session=True)
    assert offer_body(fresh, limits={})["resume_session_id"] is None


@pytest.mark.asyncio
async def test_another_pass_of_the_same_phase_resumes_its_session_and_a_new_phase_starts_fresh(db):
    """A fresh Claude Code session per revision re-reads the contract, SPEC.md and the files each time. A revision of
    the same phase continues its session with a short prompt naming what changed; another phase starts fresh."""
    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_event", {"kind": "session", "claude_session_id": "claude-work-1"}, limits={})
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})

    run.context = {**run.context, "po_answers": [{"text": "Use the blue button."}]}
    await _reenter(db, run, "work")  # the product owner's answer sends the phase back while its turn still ends
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert job.status == "offered" and job.turn_count == 2
    assert offer_body(job, limits={})["resume_session_id"] == "claude-work-1"
    assert "continues in this session" in job.turn_prompt and "do not re-read" in job.turn_prompt
    assert "product owner answered" in job.turn_prompt
    # Run 4: the answers travel in the prompt itself, not as a second fetch of the whole contract.
    assert "Use the blue button." in job.turn_prompt and "Call workflow_run_status once" not in job.turn_prompt

    await _reenter(db, run, "work", runtime_step=True)  # a pipeline turn in between: fresh, no agent session
    await _reenter(db, run, "work")  # red: back to the same phase
    await apply_event(db, job, "job_rejected", {"turn_id": job.turn_id, "reason": "pipeline_done"}, limits={})
    assert offer_body(job, limits={})["resume_session_id"] == "claude-work-1"  # the phase's own session again


@pytest.mark.asyncio
async def test_a_new_phase_starts_a_fresh_session(db):
    admin, _device, thread, run = await _device_run(db, definition=TWO_PHASES)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_event", {"kind": "session", "claude_session_id": "claude-work-1"}, limits={})
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await _reenter(db, run, "more")
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert job.status == "offered" and offer_body(job, limits={})["resume_session_id"] is None
    assert "phase 'More'" in job.turn_prompt and "workflow_run_status" in job.turn_prompt
