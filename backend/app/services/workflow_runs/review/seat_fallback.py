"""The seat review with its company fallback (``seat``): the same model on a company runtime when the seat cannot
answer, as a visible run event and only within the run's budget."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ...agent_gateway.engine_keys import ENGINE_CLAUDE_CODE
from ...agent_gateway.review_keys import ROUTE_SEAT
from ..records import record_event
from . import seat as seat_turn
from .model import REASON_MODEL_NOT_ADMITTED, ReviewAnswer, ReviewModelUnavailableError
from .seat import (
    EVENT_SEAT_FALLBACK,
    REASON_BUDGET,
    SeatReviewModel,
    SeatReviewUnavailableError,
    _keep_attempt_alive,
    seat_device,
)
from .seat_person import seat_phases

# A seat review turn that failed for a passing reason (the call failed, no answer) is asked once more before the
# company fallback; a limit, a refusal or a timeout is not (otherwise one failed Codex review call went
# straight to a fallback model the Workspace does not admit, and the run paused).
SEAT_ATTEMPTS = 2
_LASTING = ("usage_limit", "rate_limit", "seat_limit", "stopped_by_owner")


def _transient(reason: str) -> bool:
    return reason.startswith("seat_turn_failed:") and not any(word in reason for word in _LASTING)


class SeatOrCompanyReviewModel:
    """The seat review, falling back to the same model on a company runtime when the seat is unavailable."""

    def __init__(self, db: AsyncSession, run: WorkflowRun, choice: Any, seat: SeatReviewModel | None,
                 company: Callable[[], Awaitable[Any]], *, unavailable: str = "",
                 sleep: Callable[[float], Awaitable[Any]] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._db, self._run, self._choice = db, run, choice
        self._sleep, self._clock = sleep or seat_turn._wait_a_moment, clock
        self._seat, self._company_factory, self._company = seat, company, None
        self._unavailable = unavailable
        self.route = ROUTE_SEAT if seat is not None else ""

    @property
    def runtime_shared(self) -> bool:
        return bool(getattr(self._company, "runtime_shared", False))

    async def answer(self, *, system: str, user: str, images: list[Any] | None = None) -> ReviewAnswer:
        if self._seat is not None and self._company is None:
            answer = await self._seat_answer(system=system, user=user, images=images)
            if answer is not None:
                return answer
        if self._company is None:
            try:
                self._company = await self._fall_back(self._unavailable or "seat_unavailable")
            except ReviewModelUnavailableError as error:
                if not self._unavailable or error.reason != REASON_MODEL_NOT_ADMITTED:
                    raise
                # The seat's own failure is the cause; "not admitted" alone hid it.
                raise ReviewModelUnavailableError(f"{self._unavailable[:300]}; no admitted company fallback") \
                    from error
        return await self._company.answer(system=system, user=user, images=images)

    async def _seat_answer(self, *, system: str, user: str, images: list[Any] | None) -> ReviewAnswer | None:
        """The seat's answer, or ``None`` when the seat cannot give one (``self._unavailable`` says why). A full
        device (``device_busy``) is waited out and asked again, up to ``devices.busy_wait``'s limit; it never uses up
        an attempt (otherwise a run paused with ``seat_turn_failed:device_busy``)."""
        from ...devices import busy_wait

        attempt, busy_since = 0, None
        while True:
            try:
                answer = await self._seat.answer(system=system, user=user, images=images)
            except SeatReviewUnavailableError as error:
                self._unavailable = error.reason
                if busy_wait.is_busy(error.reason):
                    busy_since = self._clock() if busy_since is None else busy_since
                    waited = self._clock() - busy_since
                    if busy_wait.saturated(waited):
                        busy_wait.observe("review", "saturated", waited)
                        self._unavailable = f"device_saturated: {busy_wait.saturated_message(waited)}"
                        return None
                    await self._db.commit()  # no pool connection is held while the device is full
                    await self._sleep(busy_wait.RETRY_SECONDS)
                    await _keep_attempt_alive(self._db, self._run)
                    continue
                attempt += 1
                if attempt >= SEAT_ATTEMPTS or not _transient(error.reason):
                    return None
                continue
            if busy_since is not None:
                busy_wait.observe("review", "ran", self._clock() - busy_since)
            return answer

    async def _fall_back(self, reason: str) -> Any:
        """The company model instead of the seat: a visible event, and only within the run's budget."""
        from ..octryx.model_guard import run_budget, run_spend

        self.route = "company_fallback"
        spent, budget = await run_spend(self._db, self._run), run_budget(self._run)
        record_event(self._db, self._run, EVENT_SEAT_FALLBACK, node_id=self._run.current_node_id, detail={
            "reason": reason[:300], "model": self._choice.model, "engine": self._choice.engine,
            "route": "company", "spent_usd": round(spent, 4), "budget_usd": round(budget, 4)})
        await self._db.commit()
        if spent >= budget:
            raise ReviewModelUnavailableError(REASON_BUDGET)
        return await self._company_factory()


async def _model_not_admitted(db: AsyncSession, run: WorkflowRun, choice: Any) -> str:
    """Why the seat cannot take the review model (``''`` when it can), named before a device is asked: the gateway
    would refuse the call with ``seat_model_not_allowed`` and the run paused without saying which model (e.g.
    claude-sonnet-5-5 against a baseline without it)."""
    from ...agent_gateway.seat_policy import workspace_seat_decision

    if choice.engine != ENGINE_CLAUDE_CODE or not run.project_id:
        return ""
    decision = await workspace_seat_decision(db, str(run.project_id))
    if not decision.allowed or choice.model in decision.models:
        return ""
    return (f"review model {choice.model} is not admitted on the seat; admitted: {', '.join(decision.models)}; "
            "next: admit it in the Workspace seat models")


async def seat_review_model(db: AsyncSession, run: WorkflowRun, choice: Any,
                            company: Callable[[], Awaitable[Any]]) -> SeatOrCompanyReviewModel:
    """The seat reviewer for ``choice`` on the run's person's device, with the company fallback ready. A PR review bot
    run with several seats is offered to them phase by phase, the first device that takes it reviews
    (``seat_broadcast``); with exactly one seat it is that seat, as for a person's run."""
    from .seat_broadcast import BroadcastSeatReviewModel

    refused = await _model_not_admitted(db, run, choice)
    if refused:
        return SeatOrCompanyReviewModel(db, run, choice, None, company, unavailable=refused)
    phases, reason = [], "seat_no_person"
    for phase in await seat_phases(db, run):
        seats = []
        for person, source in phase:
            found = await seat_device(db, run, engine=choice.engine, user=person, review_call=True)
            if isinstance(found, str):
                reason = found
                continue
            seats.append(SeatReviewModel(db, run, choice, *found, person_id=person.id, source=source))
        if seats:
            phases.append(seats)
    if not phases:
        return SeatOrCompanyReviewModel(db, run, choice, None, company, unavailable=reason)
    if len(phases) == 1 and len(phases[0]) == 1:
        return SeatOrCompanyReviewModel(db, run, choice, phases[0][0], company)
    return SeatOrCompanyReviewModel(db, run, choice, BroadcastSeatReviewModel(db, run, phases), company)
