"""A device's seat at its usage limit (100 %) is remembered until its reset."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import DeviceJob
from app.models.agent.device_job import DeviceJobEvent
from app.services.devices.seat_quota import (
    UNKNOWN_RESET,
    is_limit_answer,
    is_limit_failure,
    reset_time,
    seat_limit,
    seat_limited_until,
)
from app.services.workflow_runs.records import new_chat_session
from tests.devices.device_support import device_with_grant, enable_device_runs
from tests.phased_workflow_fixtures import admin_user

LIMIT = "You've hit your weekly limit · resets Nov 13 at 11am (Europe/Zurich)"


def test_the_reset_is_read_from_the_answer_in_its_time_zone():
    said = datetime(2026, 11, 9, 15, 0)  # UTC
    assert reset_time(LIMIT, said_at=said) == datetime(2026, 11, 13, 10, 0)  # 11:00 Zurich = 10:00 UTC
    assert reset_time("You've hit your session limit · resets 7pm (Europe/Zurich)", said_at=said) == datetime(
        2026, 11, 9, 18, 0)
    assert reset_time("usage limit reached", said_at=said) == said + UNKNOWN_RESET
    assert is_limit_answer(LIMIT) and not is_limit_answer("All tests passed")


@pytest.mark.asyncio
async def test_the_seat_counts_as_limited_until_its_reset_and_a_later_success_clears_it(db):
    admin = await admin_user(db)
    device, _ = await device_with_grant(db, admin)
    project = await enable_device_runs(db)
    thread = await new_chat_session(db, admin, project.id)
    now = datetime(2026, 11, 9, 16, 0)
    job = DeviceJob(id="dj_seatquota01", device_id=device.id, owner_user_id=admin.id, session_id=thread.id,
                    folder="/tmp/x",
                    profile="seat", status="idle")
    db.add(job)
    await db.flush()
    db.add(DeviceJobEvent(job_id=job.id, seq=1, type="turn_finished", created_at=now - timedelta(hours=1),
                          body={"status": "error", "result_text": LIMIT}))
    await db.flush()
    assert await seat_limited_until(db, device.id, now=now) == datetime(2026, 11, 13, 10, 0)
    assert await seat_limited_until(db, device.id, now=datetime(2026, 11, 13, 10, 1)) is None
    # A person chooses the seat after the limit was reported: the seat is tried again.
    assert await seat_limited_until(db, device.id, now=now, chosen_at=now - timedelta(minutes=30)) is None
    assert await seat_limited_until(db, device.id, now=now, chosen_at=now - timedelta(hours=2)) == datetime(
        2026, 11, 13, 10, 0)
    db.add(DeviceJobEvent(job_id=job.id, seq=2, type="turn_finished", created_at=now - timedelta(minutes=5),
                          body={"status": "success", "result_text": "Done."}))
    await db.flush()
    assert await seat_limited_until(db, device.id, now=now) is None


@pytest.mark.asyncio
async def test_a_successful_turn_whose_summary_names_a_limit_does_not_count_as_the_seats_limit(db):
    """An implement summary listing "recipe limit reached: 1000" does not move the run off its seat. Only a
    failed turn carries the account's limit answer."""
    admin = await admin_user(db)
    device, _ = await device_with_grant(db, admin)
    project = await enable_device_runs(db)
    thread = await new_chat_session(db, admin, project.id)
    now = datetime(2026, 11, 15, 16, 10)
    job = DeviceJob(id="dj_seatquota02", device_id=device.id, owner_user_id=admin.id, session_id=thread.id,
                    folder="/tmp/x", profile="seat", status="idle")
    db.add(job)
    await db.flush()
    db.add(DeviceJobEvent(job_id=job.id, seq=1, type="turn_finished", created_at=now - timedelta(seconds=1),
                          body={"status": "success", "result_text": "Errors: `recipe limit reached: 1000`."}))
    await db.flush()
    assert await seat_limited_until(db, device.id, now=now) is None
    db.add(DeviceJobEvent(job_id=job.id, seq=2, type="turn_finished", created_at=now,
                          body={"status": "error", "result_text": "You've hit your session limit"}))
    await db.flush()
    assert await seat_limited_until(db, device.id, now=now) == now + UNKNOWN_RESET  # a failed limit answer still counts


# --- structured signals only, per engine -----------------------------------------------------------------------------

async def _seat_job(db, job_id: str, *, engine: str | None = None):
    admin = await admin_user(db)
    device, _ = await device_with_grant(db, admin)
    project = await enable_device_runs(db)
    thread = await new_chat_session(db, admin, project.id)
    job = DeviceJob(id=job_id, device_id=device.id, owner_user_id=admin.id, session_id=thread.id, folder="/tmp/x",
                    profile="seat", status="idle", engine=engine)
    db.add(job)
    await db.flush()
    return device, job


async def _finished(db, job, seq: int, at: datetime, body: dict) -> None:
    db.add(DeviceJobEvent(job_id=job.id, seq=seq, type="turn_finished", created_at=at, body=body))
    await db.flush()


def test_only_the_accounts_own_answer_counts_never_words_an_agent_wrote():
    assert not is_limit_answer("I could not finish: the API hit a rate limit, so I retried. Usage limit reached?")
    assert not is_limit_answer("Errors: `recipe limit reached: 1000`")
    assert is_limit_answer("You’ve hit your session limit · resets 7pm (Europe/Zurich)")  # typographic apostrophe
    assert is_limit_failure("rate_limit") and is_limit_failure("", "", http_status=429)
    assert not is_limit_failure("error", "the tests hit a rate limit")


@pytest.mark.asyncio
async def test_a_failed_turn_whose_text_mentions_a_rate_limit_is_not_the_seats_limit(db):
    device, job = await _seat_job(db, "dj_seatquota03")
    now = datetime(2026, 11, 15, 16, 0)
    await _finished(db, job, 1, now, {"status": "error", "result_text": "Stopped: the upstream rate limit was hit "
                                                                        "by the integration test; usage limit 100."})
    assert await seat_limited_until(db, device.id, now=now) is None


@pytest.mark.asyncio
async def test_a_structured_rate_limit_counts_with_the_reset_the_account_named(db):
    device, job = await _seat_job(db, "dj_seatquota04")
    said = datetime(2026, 11, 15, 15, 0)
    await _finished(db, job, 1, said, {"status": "error", "error": "rate_limit",
                                       "result_text": "You've hit your session limit · resets 7pm (Europe/Zurich)"})
    limit = await seat_limit(db, device.id, now=said)
    assert (limit.until, limit.reset_known) == (datetime(2026, 11, 15, 18, 0), True)


@pytest.mark.asyncio
async def test_an_http_429_counts_and_an_unnamed_reset_is_tried_again_after_an_hour(db):
    device, job = await _seat_job(db, "dj_seatquota05")
    said = datetime(2026, 11, 15, 15, 0)
    await _finished(db, job, 1, said, {"status": "error", "http_status": 429, "result_text": ""})
    limit = await seat_limit(db, device.id, now=said)
    assert (limit.until, limit.reset_known) == (said + UNKNOWN_RESET, False)
    assert reset_time("Claude AI usage limit reached|1794762000", said_at=said) == datetime(2026, 11, 15, 17, 0)
    assert reset_time("You've hit your usage limit. Try again in 1 day 2 hours", said_at=said) == said + timedelta(
        days=1, hours=2)


@pytest.mark.asyncio
async def test_a_claude_seat_limit_does_not_hold_back_the_codex_seat_of_the_same_device(db):
    device, job = await _seat_job(db, "dj_seatquota06")  # a job without engine: Claude Code
    now = datetime(2026, 11, 15, 16, 0)
    await _finished(db, job, 1, now, {"status": "error", "error": "rate_limit", "result_text": LIMIT})
    assert await seat_limited_until(db, device.id, now=now) is not None
    assert await seat_limited_until(db, device.id, engine="codex", now=now) is None
    codex = DeviceJob(id="dj_seatquota07", device_id=device.id, owner_user_id=job.owner_user_id,
                      session_id=job.session_id, folder="/tmp/y", profile="seat", status="idle", engine="codex")
    db.add(codex)
    await db.flush()
    await _finished(db, codex, 1, now, {"status": "error", "error": "usage_limit", "result_text": "Done half."})
    assert await seat_limited_until(db, device.id, engine="codex", now=now) == now + UNKNOWN_RESET
