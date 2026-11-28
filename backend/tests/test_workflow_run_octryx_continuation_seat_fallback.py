"""Seat turns refused by policy or at their usage limit continue governed on the same device."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import UserDevice
from app.services.devices.job_events import apply_event
from tests.devices.device_support import enable_device_runs
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_continuation_support import FOLDER, _confirm, _device_run, _hub, _jobs  # noqa: F401

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_a_seat_turn_refused_for_sensitive_content_continues_governed_on_the_same_device(db, monkeypatch):
    from app.models import WorkflowRunEvent
    from app.services.content_routing import conversation_state
    from app.services.workflow_runs.octryx.run_turn import EVENT_PROFILE_GOVERNED

    admin, device, thread, run = await _device_run(db)
    await enable_device_runs(db, allowed_profiles=["governed", "seat"], sensitive_content_requires_governed=True)
    dev = await db.get(UserDevice, device.id)
    dev.profiles = ["governed", "seat"]
    thread.metadata_ = {**thread.metadata_, "execution_target": {**thread.metadata_["execution_target"],
                                                                 "profile": "seat"}}

    async def _pii(session_id, key):
        return conversation_state.ConversationState(frozenset({"pii"}))

    monkeypatch.setattr(conversation_state, "load_state", _pii)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert (job.profile, job.folder, job.status, run.status) == ("governed", FOLDER, "offered", "running")
    assert thread.metadata_["execution_target"]["profile"] == "governed"
    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
                                                              WorkflowRunEvent.kind == EVENT_PROFILE_GOVERNED))).scalars()
    [event] = list(events)
    assert event.detail["to"] == "governed" and "seat" in event.detail["message"]


@pytest.mark.asyncio
async def test_a_seat_turn_the_workspace_forbids_continues_governed_on_the_same_device(db):
    from app.models import WorkflowRunEvent
    from app.services.workflow_runs.octryx.run_turn import EVENT_PROFILE_GOVERNED

    admin, device, thread, run = await _device_run(db)
    await enable_device_runs(db, allowed_profiles=["governed", "seat"])
    dev = await db.get(UserDevice, device.id)
    dev.profiles = ["governed", "seat"]
    thread.metadata_ = {**thread.metadata_, "execution_target": {**thread.metadata_["execution_target"],
                                                                 "profile": "seat"}}
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert (job.profile, job.folder, job.status, run.status) == ("governed", FOLDER, "offered", "running")
    [event] = list((await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == EVENT_PROFILE_GOVERNED))).scalars())
    assert event.detail["reason"] in {"seat_mode_forbidden", "seat_classification_unresolved"}
    assert event.detail["to"] == "governed" and "seat" in event.detail["message"]


def test_the_governed_fallback_covers_every_seat_policy_refusal():
    from app.services.agent_gateway import seat_policy_keys as keys
    from app.services.devices.device_policy import REASON_CONTENT_REQUIRES_GOVERNED
    from app.services.workflow_runs.octryx.run_turn import SEAT_FALLBACK_REASONS

    assert SEAT_FALLBACK_REASONS == {
        REASON_CONTENT_REQUIRES_GOVERNED, keys.REASON_SEAT_MODE_FORBIDDEN, keys.REASON_SEAT_REQUIRES_GOVERNED,
        keys.REASON_SEAT_CLASSIFICATION, keys.REASON_SEAT_CLASSIFICATION_UNRESOLVED,
        keys.REASON_SEAT_CLASSIFICATION_REQUIRES_GOVERNED}


@pytest.mark.asyncio
async def test_a_refused_turn_waits_visibly_is_not_resumed_by_the_device_and_continues_after_a_runtime_change(db):
    from app.services.workflow_runs.runtime_target.device_wait import resume_for_device
    from app.services.workflow_runs.runtime_target.switch import change_runtime

    admin, device, thread, run = await _device_run(db)
    thread.metadata_ = {**thread.metadata_, "execution_target": {**thread.metadata_["execution_target"],
                                                                 "folder": "/home/elsewhere"}}
    await _confirm(db, run, admin)
    waiting = run.node_state["waiting"]
    assert (run.status, run.waiting_kind) == ("waiting", "waiting_for_device") and waiting["refused"] is True
    assert "folder" in waiting["question"] and await _jobs(db, thread) == []
    assert await resume_for_device(db, device.id) == [] and run.status == "waiting"

    await change_runtime(db, run, user=admin, raw={"kind": "device", "device_id": device.id, "folder": FOLDER,
                                                   "profile": "governed"})
    [job] = await _jobs(db, thread)
    assert (run.status, job.folder, job.status) == ("running", FOLDER, "offered")


def test_a_usage_limit_on_the_device_is_named_with_its_reset_and_the_remedy():
    from app.services.workflow_runs.octryx.turn_failures import CODE_SEAT_LIMIT, failed_turn_explanation

    code, message = failed_turn_explanation("error", "You've hit your weekly limit · resets Nov 13 at 11am")
    assert code == CODE_SEAT_LIMIT and "resets Nov 13" in message and "governed" in message
    code, message = failed_turn_explanation("error", "Something else broke")
    assert code == "device_turn_error" and "Something else broke" in message
    assert failed_turn_explanation("api_error_504", "")[0] == "device_turn_api_error_504"


@pytest.mark.asyncio
async def test_a_seat_turn_at_its_usage_limit_runs_again_governed_without_stopping(db):
    from app.models import WorkflowRunEvent
    from app.services.workflow_runs.octryx.run_turn import EVENT_PROFILE_GOVERNED
    from app.services.workflow_runs.runtime_target.target import stored_target, with_target

    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    run.context = with_target(run.context, {**(stored_target(run) or {
        "kind": "device", "device_id": job.device_id, "folder": FOLDER}), "profile": "seat"}, actor_id=None)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "error",
                                                 "result_text": "You've hit your weekly limit · resets Nov 13"},
                      limits={})
    assert (run.status, run.pause_reason) == ("running", None)
    kinds = [e.kind for e in (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id))).scalars()]
    assert EVENT_PROFILE_GOVERNED in kinds and "seat_usage_limit" in kinds
    assert kinds.count("device_continuation_started") == 2
    assert stored_target(run)["profile"] == "governed"


@pytest.mark.asyncio
async def test_a_codex_seat_limit_takes_its_reset_from_the_recorded_rate_limits(db):
    from datetime import UTC, datetime

    from app.services.workflow_runs.octryx.seat_fallback import FALLBACK_KEY
    from app.services.workflow_runs.runtime_target.target import stored_target, with_target

    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    run.context = with_target(run.context, {**(stored_target(run) or {
        "kind": "device", "device_id": job.device_id, "folder": FOLDER}), "profile": "seat"}, actor_id=None)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    resets = int(datetime.now(UTC).timestamp()) + 3600  # in the future: a past reset continues at once
    await apply_event(db, job, "turn_finished", {
        "turn_id": job.turn_id, "status": "error", "error": "usage_limit", "engine": "codex",
        "result_text": "Die Chrome-Prüfung ist grün.",
        "seat_rate_limits": {"primary": {"used_percent": 100.0, "window_minutes": 300, "resets_at": resets},
                             "secondary": {"used_percent": 54.0, "window_minutes": 10080, "resets_at": resets + 9}}},
        limits={})
    fallback = run.context[FALLBACK_KEY]
    assert fallback["reset_known"] is True
    assert datetime.fromisoformat(fallback["until"]) == datetime.fromtimestamp(resets, tz=UTC)
