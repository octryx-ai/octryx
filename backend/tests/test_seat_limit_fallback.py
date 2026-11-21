"""A run whose seat is at its usage limit: the company model of the same class, a
pause when there is none, back to the seat after the reset, and the company calls count against the run's budget."""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.models import UsageEvent
from app.services.devices.job_events import apply_event
from app.services.workflow_runs.octryx import model_guard, seat_fallback
from app.services.workflow_runs.octryx.model_guard import REASON_RUN_BUDGET, guard_model_call, run_spend
from app.services.workflow_runs.octryx.run_turn import EVENT_PROFILE_GOVERNED
from app.services.workflow_runs.records import main_session_id
from app.time_utils import utc_now
from tests.phase_seat_models_support import seat_admitted  # noqa: F401 - fixture
from tests.phase_sessions_models_support import SONNET, _events, _seat_run, _with_phase
from tests.workflow_run_octryx_continuation_support import DEFINITION, _confirm, _hub, _jobs, _reenter  # noqa: F401

COMPANY_SONNET = "company-sonnet"
LIMIT = {"status": "error", "error": "rate_limit", "result_text": "You've hit your session limit · resets 7pm "
                                                                  "(Europe/Zurich)"}


@pytest.fixture
def company_aliases(monkeypatch, seat_admitted):  # noqa: F811
    """The Workspace's admitted company aliases (``aliases``), also admitted as device models."""
    aliases: list[SimpleNamespace] = []

    async def admitted(*_a, **_k):
        return tuple(aliases)

    monkeypatch.setattr(seat_fallback, "admitted_company_aliases", admitted)
    seat_admitted["models"] |= {SONNET, COMPANY_SONNET, "company-opus"}
    return aliases


def _alias(alias: str, **fields) -> SimpleNamespace:
    return SimpleNamespace(alias=alias, display_name=fields.get("display_name", ""),
                           model_group=fields.get("model_group", ""), served_model_ids=frozenset())


async def _seat_turn_hits_its_limit(db):
    admin, thread, run = await _seat_run(db, _with_phase(DEFINITION, "work", model=SONNET))
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert (job.profile, job.turn_model) == ("seat", SONNET)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, **LIMIT}, limits={})
    return thread, run


def _newest(jobs):
    return max(jobs, key=lambda job: (job.created_at, job.turn_count))


@pytest.mark.asyncio
async def test_a_limited_sonnet_seat_falls_back_to_a_sonnet_class_company_model_never_a_bigger_one(db,
                                                                                                    company_aliases):
    company_aliases += [_alias("company-opus", model_group="claude-opus-5-5"),
                        _alias(COMPANY_SONNET, display_name="Claude Sonnet 5.5")]
    thread, run = await _seat_turn_hits_its_limit(db)
    assert (run.status, run.pause_reason) == ("running", None)
    job = _newest(await _jobs(db, thread))
    assert (job.profile, job.turn_model, job.status) == ("governed", COMPANY_SONNET, "offered")
    [switched] = await _events(db, run, EVENT_PROFILE_GOVERNED)
    assert switched.detail["reset_known"] is True and switched.detail["until"] and "returns to your seat" in \
        switched.detail["message"]
    [chosen] = await _events(db, run, seat_fallback.EVENT_FALLBACK_MODEL)
    assert (chosen.detail["seat_model"], chosen.detail["company_model"]) == (SONNET, COMPANY_SONNET)
    view = seat_fallback.fallback_view(run)
    assert view["on_company_fallback"] and view["until"] == switched.detail["until"]
    assert view["message"].startswith("On company fallback until ")


@pytest.mark.asyncio
async def test_without_a_same_class_company_model_the_run_pauses_with_the_seat_model_and_the_reset(db,
                                                                                                    company_aliases):
    company_aliases.append(_alias("company-opus", model_group="claude-opus-5-5"))
    thread, run = await _seat_turn_hits_its_limit(db)
    assert (run.status, run.pause_reason) == ("paused", "seat_limit")
    pause = run.node_state["pause"]
    assert pause["code"] == seat_fallback.REASON_NO_SAME_CLASS
    assert (pause["seat_model"], pause["class"]) == (SONNET, "sonnet") and pause["reset_at"]
    assert all(job.profile == "seat" for job in await _jobs(db, thread))  # nothing started on Opus


@pytest.mark.asyncio
async def test_after_the_reset_the_next_turn_runs_on_the_seat_again_with_an_event(db, company_aliases):
    company_aliases.append(_alias(COMPANY_SONNET, display_name="Claude Sonnet 5.5"))
    thread, run = await _seat_turn_hits_its_limit(db)
    governed = _newest(await _jobs(db, thread))
    await apply_event(db, governed, "job_accepted", {"turn_id": governed.turn_id}, limits={})
    state = seat_fallback.fallback_state(run)
    run.context = {**run.context, seat_fallback.FALLBACK_KEY: {
        **state, "until": (utc_now() - timedelta(minutes=1)).isoformat()}}  # the reset has passed
    await _reenter(db, run, "work")
    await apply_event(db, governed, "turn_finished", {"turn_id": governed.turn_id, "status": "success"}, limits={})
    job = _newest(await _jobs(db, thread))
    assert (job.profile, job.turn_model, job.status) == ("seat", SONNET, "offered")
    [returned] = await _events(db, run, seat_fallback.EVENT_SEAT_RETURNED)
    assert returned.detail["reset_known"] is True and returned.detail["reset_at"]
    assert seat_fallback.fallback_state(run) is None and seat_fallback.fallback_view(run) is None


@pytest.mark.asyncio
async def test_the_company_calls_after_the_switch_count_against_the_runs_budget(db, company_aliases):
    company_aliases.append(_alias(COMPANY_SONNET, display_name="Claude Sonnet 5.5"))
    thread, run = await _seat_turn_hits_its_limit(db)
    session_id = await main_session_id(db, run)
    before = await run_spend(db, run)
    db.add(UsageEvent(id=str(uuid.uuid4()), session_id=session_id, user_id=thread.user_id, provider="litellm",
                      model=COMPANY_SONNET, tokens_in=1_000_000, tokens_out=0, cost=0.0))
    await db.flush()
    model_guard._spend_cache.clear()
    assert await run_spend(db, run) == pytest.approx(before + 2.0)  # sonnet list price, $2 per million in
    run.limits = {**dict(run.limits or {}), "budget": {"cost_usd": 1.0}}
    guarded = await guard_model_call(db, session_id, {"model": COMPANY_SONNET})
    assert guarded.refusal == REASON_RUN_BUDGET
