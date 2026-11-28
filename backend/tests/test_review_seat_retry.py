"""A seat review that failed for a passing reason is asked once more before the company fallback,
and a pause names the seat's failure."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.review import seat_fallback as seat_module
from app.services.workflow_runs.review.model import REASON_MODEL_NOT_ADMITTED, ReviewModelUnavailableError
from app.services.workflow_runs.review.seat import SeatReviewUnavailableError
from app.services.workflow_runs.review.seat_fallback import SeatOrCompanyReviewModel


class _Seat:
    def __init__(self, failures: list[str]) -> None:
        self.failures, self.calls = list(failures), 0

    async def answer(self, **_kwargs):
        self.calls += 1
        if self.failures:
            raise SeatReviewUnavailableError(self.failures.pop(0))
        return "seat answer"


def _model(seat: _Seat, monkeypatch) -> SeatOrCompanyReviewModel:
    async def not_admitted(self, reason):
        raise ReviewModelUnavailableError(REASON_MODEL_NOT_ADMITTED)

    monkeypatch.setattr(SeatOrCompanyReviewModel, "_fall_back", not_admitted)
    return SeatOrCompanyReviewModel(None, None, None, seat, None)


@pytest.mark.asyncio
async def test_a_failed_seat_call_is_asked_once_more(monkeypatch):
    seat = _Seat(["seat_turn_failed:review_call_failed"])
    assert await _model(seat, monkeypatch).answer(system="s", user="u") == "seat answer"
    assert seat.calls == 2


@pytest.mark.asyncio
async def test_without_an_admitted_fallback_the_pause_names_the_seats_failure(monkeypatch):
    seat = _Seat(["seat_turn_failed:review_call_failed"] * 2)
    with pytest.raises(ReviewModelUnavailableError) as raised:
        await _model(seat, monkeypatch).answer(system="s", user="u")
    assert seat.calls == seat_module.SEAT_ATTEMPTS
    assert raised.value.reason.startswith("seat_turn_failed:review_call_failed; no admitted company fallback")


@pytest.mark.asyncio
async def test_a_seat_limit_is_not_asked_again(monkeypatch):
    seat = _Seat(["seat_turn_failed:usage_limit", "seat_turn_failed:usage_limit"])
    with pytest.raises(ReviewModelUnavailableError) as raised:
        await _model(seat, monkeypatch).answer(system="s", user="u")
    assert seat.calls == 1 and "usage_limit" in raised.value.reason


class _Db:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _row) -> None:
        return None


class _Run:
    node_state: dict = {}


def _waiting_model(seat: _Seat, monkeypatch, clock: list[float]) -> SeatOrCompanyReviewModel:
    async def not_admitted(self, reason):
        raise ReviewModelUnavailableError(REASON_MODEL_NOT_ADMITTED)

    async def sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(SeatOrCompanyReviewModel, "_fall_back", not_admitted)
    return SeatOrCompanyReviewModel(_Db(), _Run(), None, seat, None, sleep=sleep, clock=lambda: clock[0])


@pytest.mark.asyncio
async def test_a_full_device_is_waited_out_and_the_review_runs_once_it_is_free(monkeypatch):
    seat = _Seat(["seat_refused:device_busy", "seat_turn_failed:device_busy", "seat_turn_failed:device_busy",
                  "seat_turn_failed:review_call_failed"])
    assert await _waiting_model(seat, monkeypatch, [0.0]).answer(system="s", user="u") == "seat answer"
    assert seat.calls == 5


@pytest.mark.asyncio
async def test_a_device_full_past_the_limit_pauses_saying_it_was_saturated(monkeypatch):
    from app.services.devices import busy_wait

    seat = _Seat(["seat_turn_failed:device_busy"] * 1000)
    with pytest.raises(ReviewModelUnavailableError) as raised:
        await _waiting_model(seat, monkeypatch, [0.0]).answer(system="s", user="u")
    assert raised.value.reason.startswith("device_saturated: The device was saturated for")
    assert seat.calls == int(busy_wait.MAX_WAIT_SECONDS // busy_wait.RETRY_SECONDS) + 1


@pytest.mark.asyncio
async def test_writing_the_hands_on_scenarios_waits_for_a_full_device_instead_of_going_red(monkeypatch):
    from types import SimpleNamespace

    from app.services.workflow_runs.hands_on import generate, invalid

    class _ScenarioSeat(_Seat):
        async def answer(self, **kwargs):
            await super().answer(**kwargs)
            return SimpleNamespace(answer={"scenarios": ["s1"]}, usage="usage")

    async def keeps(_db, _run):
        return True

    async def notes(_db, _run):
        return ""

    monkeypatch.setattr(invalid, "keeps_data", keeps)
    monkeypatch.setattr(invalid, "writer_notes", notes)
    monkeypatch.setattr(generate, "_checked", lambda answer, *_rest: answer["scenarios"])
    seat = _ScenarioSeat(["seat_turn_failed:device_busy"] * 3)
    run = _Run()
    run.id = "run-1"
    model = _waiting_model(seat, monkeypatch, [0.0])
    scenarios, problem, _usage = await generate.write_scenarios(None, run, model, "task")
    assert (scenarios, problem, seat.calls) == (["s1"], "", 4)
