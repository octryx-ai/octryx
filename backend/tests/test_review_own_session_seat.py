"""The seat review is a separate tool-less device turn on the person's own subscription, with a visible company fallback that counts against the run budget."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Session, UsageEvent, UserDevice, WorkflowRun, WorkflowRunEvent
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.review_own_session_support import (  # noqa: F401
    DEFAULT,
    HAIKU,
    TERRA,
    _awaiting_review,
    _codex_policy,
    workspace_runtimes,
)
from tests.workflow_run_review_support import PASS

# --- seat route ------------------------------------------------------------------------------------------------


@pytest.fixture
def device_side(monkeypatch):
    """The person's device: reachable, starting turns without the dispatch policy, and answering a review turn as
    the launcher does (fetch the request through its review session, post the answer, finish the turn)."""
    import app.services.devices.chat_turn as chat_turn
    import app.services.workflow_runs.review.seat as seat
    import app.services.workflow_runs.review.seat_control as seat_control
    from app.services.devices.hub import device_hub
    from app.services.devices.job_engine import job_engine
    from app.services.devices.job_events import apply_event
    from app.services.devices.job_offer import offer_body
    from app.services.devices.jobs import start_turn
    from app.services.devices.jobs_channel import _thread_run

    state = SimpleNamespace(reachable=True, refuse="", offers=[], requests=[], denied=[], answer=PASS)
    monkeypatch.setattr(device_hub, "reachable", lambda device: state.reachable)

    async def start_device_turn(db, *, user_id, prompt, target, session_id="", fresh_session=False, **kwargs):
        if state.refuse:
            return chat_turn.DeviceTurnRefusal("denied", state.refuse, 403)
        thread = await db.get(Session, session_id)
        device = await db.get(UserDevice, target["device_id"])
        job = await start_turn(db, owner_user_id=user_id, device=device, session_id=thread.id,
                               workspace_id=thread.project_id, folder=target["folder"], profile=target["profile"],
                               prompt=prompt, model=target["model"], fresh_session=fresh_session)
        return chat_turn.DeviceTurnStarted(session=thread, job_id=job.id)

    async def device_answers(seconds):
        import json

        from app.services.agent_gateway.analysis_tools import review_tool_decision

        db, job = state.db, None
        job = (await db.execute(select(DeviceJob).where(DeviceJob.turn_state == "pending"))).scalars().first()
        if job is None:
            return
        state.offers.append(offer_body(job, limits={}, **await _thread_run(db, job), engine=await job_engine(db, job)))
        job.turn_state = "sent"
        gateway = Session(user_id=job.owner_user_id, project_id=job.workspace_id, status="active",
                          origin="model_gateway", metadata_={})
        db.add(gateway)
        await db.flush()
        assert await seat_control.mark_review_session(db, gateway, job.id, job.owner_user_id)
        state.denied.append(review_tool_decision(gateway, {"tool_name": "Bash"}))
        request = await seat_control.review_request_for(db, gateway, job.owner_user_id)
        state.requests.append(request)
        assert await seat_control.store_review_answer(db, gateway, job.owner_user_id, {
            "turn_id": request["turn_id"], "text": json.dumps(state.answer), "model": request["model"],
            "usage": {"input_tokens": 200, "output_tokens": 40}}) is None
        await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
        await db.commit()

    monkeypatch.setattr(chat_turn, "start_device_turn", start_device_turn)
    monkeypatch.setattr(seat, "_wait_a_moment", device_answers)
    return state


async def _seat_run(db, tmp_path, device_side, *, workspace_policy=None):
    from tests.phased_workflow_fixtures import admin_user

    device = UserDevice(owner_user_id=(await admin_user(db)).id, name="Mac", name_key=f"mac-{uuid.uuid4().hex[:6]}",
                        os="macos", public_key="k", profiles=["seat", "governed"], folders=[str(tmp_path)])
    db.add(device)
    await db.flush()
    run, session = await _awaiting_review(db, tmp_path / "seat", workspace_policy=workspace_policy, target={
        "kind": "device", "device_id": device.id, "folder": str(tmp_path), "profile": "seat"})
    device_side.db = db
    return run, session, device


@pytest.mark.asyncio
async def test_the_seat_review_is_a_separate_tool_less_turn_with_no_author_history(db, tmp_path, device_side):
    from app.services.workflow_runs.records import active_run_for_session

    run, session, device = await _seat_run(db, tmp_path, device_side)
    assert await run_due_reviews(db) == 1
    await db.refresh(run)
    assert run.status == "completed"
    [offer] = device_side.offers
    # A review call: bound to no run (no contract, no phase tools), a fresh session, the review model on the seat.
    assert offer["review_call"] is True and offer["workflow_run_id"] is None
    assert (offer["profile"], offer["model"], offer["resume_session_id"]) == ("seat", DEFAULT, None)
    assert "subagents" not in offer and "browser" not in offer and "local_decisions" not in offer
    [request] = device_side.requests
    assert set(request) == {"turn_id", "system", "user", "images", "model", "engine"}  # no tools, no history
    assert "Done." not in request["user"]  # the author's answer is never shown
    assert device_side.denied[0].reason == "review_tool_not_allowed"  # any tool call is denied at the gateway
    job = (await db.execute(select(DeviceJob).where(DeviceJob.device_id == device.id))).scalar_one()
    assert job.session_id != session.id and await active_run_for_session(db, job.session_id) is None
    thread = await db.get(Session, job.session_id)
    assert "review_request" not in thread.metadata_ and "review_answer" not in thread.metadata_  # cleared
    review = run.context["review"]
    assert (review["reviewer_route"], review["reviewer_route_used"], review["reviewer_engine"]) == (
        "seat", "seat", "claude_code")
    usage = (await db.execute(select(UsageEvent).where(UsageEvent.dispatch_owner == "workflow_run_review"))).scalar_one()
    assert (usage.model, usage.provider, float(usage.cost), usage.tokens_in) == (DEFAULT, "anthropic_seat", 0.0, 200)


@pytest.mark.asyncio
async def test_a_codex_seat_run_is_reviewed_on_the_codex_seat(db, tmp_path, device_side):
    run, _, device = await _seat_run(db, tmp_path, device_side, workspace_policy=_codex_policy())
    assert await run_due_reviews(db) == 1
    [offer] = device_side.offers
    assert (offer["model"], offer["engine"], offer["review_call"]) == (TERRA, "codex", True)
    job = (await db.execute(select(DeviceJob).where(DeviceJob.device_id == device.id))).scalar_one()
    assert job.engine == "codex"
    usage = (await db.execute(select(UsageEvent).where(UsageEvent.dispatch_owner == "workflow_run_review"))).scalar_one()
    assert (usage.model, usage.provider) == (TERRA, "openai_codex_seat")


@pytest.mark.asyncio
async def test_an_unavailable_seat_falls_back_visibly_and_the_spend_counts_against_the_budget(
        db, tmp_path, device_side, workspace_runtimes):  # noqa: F811
    from app.services.workflow_runs.octryx import model_guard

    device_side.reachable = False
    run, _, _ = await _seat_run(db, tmp_path, device_side)
    assert await run_due_reviews(db) == 1
    await db.refresh(run)
    assert run.status == "completed" and device_side.offers == []
    [fallback] = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "review_seat_fallback"))).scalars().all()
    assert (fallback.detail["reason"], fallback.detail["model"], fallback.detail["route"]) == (
        "seat_device_offline", DEFAULT, "company")
    assert {model for model, _ in workspace_runtimes.called} == {DEFAULT}
    assert run.context["review"]["reviewer_route_used"] == "company_fallback"
    model_guard._spend_cache.pop(run.id, None)  # read before the fallback call (the guard's 10 s cache)
    assert await model_guard.run_spend(db, await db.get(WorkflowRun, run.id)) > 0  # the governed review counts

    # A refused seat turn falls back the same way.
    device_side.reachable, device_side.refuse = True, "seat_mode_forbidden"
    second, _, _ = await _seat_run(db, tmp_path / "2", device_side)
    assert await run_due_reviews(db) == 1
    reasons = [row.detail["reason"] for row in (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == second.id, WorkflowRunEvent.kind == "review_seat_fallback"))).scalars()]
    assert reasons == ["seat_refused:seat_mode_forbidden"]


@pytest.mark.asyncio
async def test_no_fallback_review_once_the_run_budget_is_used_up(db, tmp_path, device_side, workspace_runtimes):  # noqa: F811
    from app.services.workflow_runs.records import main_session_id

    device_side.reachable = False
    run, _, _ = await _seat_run(db, tmp_path, device_side)
    run.limits = {**dict(run.limits or {}), "budget": {"cost_usd": 0.0001}}
    db.add(UsageEvent(id=str(uuid.uuid4()), session_id=await main_session_id(db, run), user_id=run.requested_by,
                      provider="bedrock", model="claude-sonnet-5-5", tokens_in=10_000, tokens_out=1_000, cost=0.03))
    await db.commit()
    assert await run_due_reviews(db) == 1
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "review_no_decision")
    assert "workflow_run_budget_exhausted" in run.node_state["pause"]["message"]
    assert workspace_runtimes.called == []


@pytest.mark.asyncio
async def test_a_seat_attempt_that_still_waits_keeps_itself_alive_for_the_sweep(db, tmp_path, device_side):
    """An attempt of several seat calls can outlive STALE_ATTEMPT_MINUTES; the sweep must not start it again next to
    itself. While it waits on the device its started_at moves on."""
    from datetime import timedelta

    from app.services.workflow_runs.review.seat import SeatReviewModel
    from app.time_utils import utc_now

    run, _session, device = await _seat_run(db, tmp_path, device_side)
    old = (utc_now() - timedelta(minutes=10)).isoformat()
    run.node_state = {**dict(run.node_state or {}), "waiting": {**dict(run.node_state["waiting"]), "started_at": old}}
    await db.commit()
    model = SeatReviewModel(db, run, SimpleNamespace(model=HAIKU, engine="claude_code"), device, str(tmp_path))
    await model._heartbeat()
    await db.refresh(run)
    assert run.node_state["waiting"]["started_at"] > old
    run.node_state = {**dict(run.node_state), "waiting": {}}  # no attempt running: nothing is written
    await db.commit()
    await model._heartbeat()
    await db.refresh(run)
    assert "started_at" not in run.node_state["waiting"]
