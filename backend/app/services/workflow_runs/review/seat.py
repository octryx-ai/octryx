"""The reviewer on the run's person's own seat: a separate, tool-less device turn."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ....models import DeviceJob, Session, User, UserDevice, WorkflowRun
from ...agent_gateway.engine_keys import ENGINE_CLAUDE_CODE, ENGINE_CODEX
from ...agent_gateway.review_keys import ROUTE_SEAT
from ..records import record_event
from .model import ReviewAnswer, answer_object, call_usage
from .seat_person import SOURCE_REQUESTER, folderless_devices

logger = logging.getLogger(__name__)

REVIEW_PURPOSE = "workflow_run_review"
PURPOSE_KEY = "purpose"
RUN_KEY = "review_of_run"
REQUEST_KEY = "review_request"
ANSWER_KEY = "review_answer"
GATEWAY_REVIEW_JOB_KEY = "review_job_id"
EVENT_SEAT_SESSION = "review_seat_session"
EVENT_SEAT_FALLBACK = "review_seat_fallback"
REASON_BUDGET = "workflow_run_budget_exhausted"
CALL_TIMEOUT_SECONDS = 300
POLL_SECONDS = 2.0
# How often a waiting attempt says it is alive (well below runner.STALE_ATTEMPT_MINUTES).
HEARTBEAT_SECONDS = 60.0
TURN_PROMPT = ("Independent review of a workflow run. The launcher fetches the reviewer's request from the platform "
               "and answers it with one tool-less model call.")
SEAT_PROVIDERS = {"claude_code": "anthropic_seat", ENGINE_CODEX: "openai_codex_seat"}
FINISHED_JOB_STATUSES = ("rejected", "failed", "device_lost", "closed")


class SeatReviewUnavailableError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(f"seat review unavailable: {reason}")
        self.reason = reason


def is_review_thread(session: Session | None) -> bool:
    return session is not None and dict(session.metadata_ or {}).get(PURPOSE_KEY) == REVIEW_PURPOSE


async def seat_device(db: AsyncSession, run: WorkflowRun, *, engine: str = ENGINE_CLAUDE_CODE,
                      user: User | None = None, review_call: bool = False) -> tuple[UserDevice, str] | str:
    from ...devices.hub import device_hub
    from ...devices.seat_quota import seat_limited_until
    from ..runtime_target.auto import _known_folders, _usable_devices, seat_exhausted
    from ..runtime_target.target import KIND_DEVICE, stored_target

    if user is None:
        user = await db.get(User, run.requested_by) if run.requested_by else None
    if user is None:
        return "seat_no_person"
    if await seat_exhausted(db, user.id):
        return "seat_usage_limit"
    target = stored_target(run) or {}
    candidates: list[tuple[UserDevice, str]] = []
    if target.get("kind") == KIND_DEVICE and target.get("device_id") and target.get("folder"):
        device = await db.get(UserDevice, str(target["device_id"]))
        if device is not None and device.owner_user_id == user.id:
            candidates.append((device, str(target["folder"])))
    candidates += [pair for pair in await _usable_devices(db, user, await _known_folders(db, user.id, run.repository))
                   if all(pair[0].id != known.id for known, _ in candidates)]
    if review_call:
        candidates += await folderless_devices(db, user, [device for device, _ in candidates])
    reason = "seat_no_device"
    for device, folder in candidates:
        if ROUTE_SEAT not in [str(item) for item in device.profiles or []]:
            reason = "seat_profile_not_on_device"
            continue
        if device.paused or not device_hub.reachable(device):
            reason = "seat_device_offline"
            continue
        # The run's engine only: a Claude seat at its limit does not hold back the Codex seat.
        if await seat_limited_until(db, device.id, engine=engine) is not None:
            reason = "seat_usage_limit"
            continue
        return device, folder
    return reason


def encoded_images(images: list[Any] | None) -> list[dict[str, str]]:
    return [{"name": str(screen.name), "media_type": str(screen.media_type),
             "data": base64.b64encode(screen.data).decode()} for screen in images or []]


async def _wait_a_moment(seconds: float) -> None:
    await asyncio.sleep(seconds)


class SeatReviewModel:
    runtime_shared = False

    def __init__(self, db: AsyncSession, run: WorkflowRun, choice: Any, device: UserDevice, folder: str, *,
                 sleep: Callable[[float], Awaitable[Any]] | None = None, clock: Callable[[], float] = time.monotonic,
                 timeout: float = CALL_TIMEOUT_SECONDS, person_id: str | None = None,
                 source: str = SOURCE_REQUESTER) -> None:
        self._db, self._run, self._choice = db, run, choice
        self._device, self._folder = device, folder
        # Whose seat: the device's owner, who owns the review thread too (the dispatch gate asks for both).
        self._person_id, self._source = person_id or run.requested_by, source
        self._sleep, self._clock, self._timeout = sleep or _wait_a_moment, clock, timeout
        self._thread: Session | None = None

    async def _review_thread(self) -> Session:
        if self._thread is None:
            thread = Session(user_id=self._person_id, project_id=self._run.project_id, status="active",
                             origin="chat", metadata_={PURPOSE_KEY: REVIEW_PURPOSE, RUN_KEY: self._run.id,
                                                       "title": "Independent review"})
            self._db.add(thread)
            await self._db.flush()
            self._thread = thread
            record_event(self._db, self._run, EVENT_SEAT_SESSION, node_id=self._run.current_node_id, detail={
                "thread_id": thread.id, "device_id": self._device.id, "model": self._choice.model,
                "engine": self._choice.engine, "seat_user_id": self._person_id, "seat_source": self._source})
        return self._thread

    async def answer(self, *, system: str, user: str, images: list[Any] | None = None) -> ReviewAnswer:
        job, thread = await self.start(system=system, user=user, images=images)
        return await self.finish(job, thread)

    async def start(self, *, system: str, user: str, images: list[Any] | None = None) -> tuple[DeviceJob, Session]:
        from ...devices.chat_turn import DeviceTurnStarted, start_device_turn

        db = self._db
        thread = await self._review_thread()
        # The device's last_seen_at moves every few seconds and the dispatch gate reads it from this session: read it
        # again right before the turn.
        await db.refresh(self._device)
        started = await start_device_turn(
            db, user_id=self._person_id, prompt=TURN_PROMPT, session_id=thread.id, fresh_session=True,
            target={"kind": "device", "device_id": self._device.id, "folder": self._folder, "profile": ROUTE_SEAT,
                    "model": self._choice.model})
        if not isinstance(started, DeviceTurnStarted):
            await db.commit()  # the thread and its event stay: the run shows that the seat was tried
            raise SeatReviewUnavailableError(f"seat_refused:{started.reason}")
        job = await db.get(DeviceJob, started.job_id)
        job.engine = self._choice.engine  # the run's engine: a Codex run is reviewed by Codex, never the other way
        metadata = {key: value for key, value in dict(thread.metadata_ or {}).items() if key != ANSWER_KEY}
        thread.metadata_ = {**metadata, REQUEST_KEY: {
            "turn_id": job.turn_id, "system": system, "user": user, "images": encoded_images(images),
            "model": self._choice.model, "engine": self._choice.engine}}
        flag_modified(thread, "metadata_")
        await db.commit()
        return job, thread

    async def finish(self, job: DeviceJob, thread: Session) -> ReviewAnswer:
        db = self._db
        try:
            answered = await self._wait(job, thread)
        finally:
            metadata = dict(thread.metadata_ or {})
            metadata.pop(REQUEST_KEY, None)
            metadata.pop(ANSWER_KEY, None)
            thread.metadata_ = metadata
            flag_modified(thread, "metadata_")
            await db.commit()
        usage = dict(answered.get("usage") or {})
        model = str(answered.get("model") or job.model or self._choice.model)[:200]
        return ReviewAnswer(answer_object(str(answered.get("text") or "")), call_usage(
            model, SEAT_PROVIDERS.get(self._choice.engine, "seat"), ROUTE_SEAT,
            int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), route=ROUTE_SEAT))

    async def _wait(self, job: DeviceJob, thread: Session) -> dict[str, Any]:
        from app.services.devices.job_state import DeviceJobError

        from ...devices.jobs import request_stop

        turn_id, deadline = job.turn_id, self._clock() + self._timeout
        beat = self._clock()
        while True:
            await self._sleep(POLL_SECONDS)
            if self._clock() - beat >= HEARTBEAT_SECONDS:
                beat = self._clock()
                await self._heartbeat()
            await self._db.refresh(job)
            await self._db.refresh(thread)
            answer = dict(thread.metadata_ or {}).get(ANSWER_KEY)
            mine = isinstance(answer, dict) and answer.get("turn_id") == turn_id
            if job.turn_id != turn_id or job.status in FINISHED_JOB_STATUSES or job.turn_state in ("rejected",
                                                                                                   "cancelled"):
                raise SeatReviewUnavailableError(f"seat_turn_failed:{job.status_reason or job.status}")
            if job.turn_state == "done":
                if mine:
                    return answer
                raise SeatReviewUnavailableError(f"seat_turn_failed:{job.status_reason or 'no_answer'}")
            if self._clock() >= deadline:
                with contextlib.suppress(DeviceJobError):
                    await request_stop(self._db, job, actor_id=job.owner_user_id)
                await self._db.commit()
                raise SeatReviewUnavailableError("seat_timeout")


    async def _heartbeat(self) -> None:
        await _keep_attempt_alive(self._db, self._run)


async def _keep_attempt_alive(db: AsyncSession, run: WorkflowRun) -> None:
    # Moving started_at keeps the review sweep from starting a still-running attempt again next to itself.
    from ....time_utils import utc_now

    await db.refresh(run)
    state = dict(run.node_state or {})
    waiting = dict(state.get("waiting") or {})
    if not waiting.get("started_at"):
        return
    run.node_state = {**state, "waiting": {**waiting, "started_at": utc_now().isoformat()}}
    flag_modified(run, "node_state")
    await db.commit()


__all__ = ["ANSWER_KEY", "EVENT_SEAT_FALLBACK", "EVENT_SEAT_SESSION", "REQUEST_KEY", "REVIEW_PURPOSE",
           "SeatReviewModel", "SeatReviewUnavailableError", "is_review_thread", "seat_device"]
