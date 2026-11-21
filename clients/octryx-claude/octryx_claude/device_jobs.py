"""The device's job manager: accept or reject turns, run them, ask for approvals, stop them.

For every ``job_offer`` the device re-checks locally, whatever the platform decided:

- not paused (local ``device pause`` or the platform's pause), else ``device_paused``;
- fewer running turns than the device's own limit (default 6, ``device parallel 1-8``), else ``device_busy``; a
  turn the offer marks ``slot_exempt`` (a team's git work or coordinator answer on its run's main thread) is not
  counted and never waits for a slot;
- the folder's realpath (symlinks resolved) inside the local allowlist, else ``folder_not_allowlisted_on_device``;
- the folder really readable by this process (macOS privacy blocks a LaunchAgent from external volumes), else
  ``device_folder_not_accessible`` with the interpreter to allow (``device_folder_access``), instead of a Claude
  Code start that hangs until the SDK's initialize timeout;
- the profile available here (``seat`` needs the seat login), else ``profile_unavailable_on_device``;
- a requested model is a well-formed model id, else ``model_invalid``; whether the profile offers it is checked
  against this session's own client policy (``device_session``), else ``model_not_offered``.

Only the prompt, folder, profile, model, Workspace, resume id and workflow run id (the run the chat thread follows;
its session is bound to it at registration after the platform's own checks, and the folder's repository must be that
run's, ``device_session``) are read from the offer; any other field (settings,
rules, MCP servers, a permission mode) is ignored. Each accepted turn runs as an ordinary octryx-claude session
(``device_session``) through the SDK (``device_sdk``), and everything it reports goes through the outbox
(``ChannelClient.send_job``) in order.

Approvals: Claude Code's permission prompt becomes ``approval_request`` with ``expires_at``; the owner's decision
arrives as ``approval_decision``. No decision in time is a deny here, on the device's own clock
(``approval_resolved {timed_out}`` tells the platform). Stop: ``interrupt()``, then ``disconnect()`` after 10 s.

Restarts: the running turns are kept in ``device-running.json``. A turn that was still listed when the service
started again (an update, a crash, a kill) is reported ``turn_finished {status: failed, reason:
service_restarted}`` once the channel is connected, so the platform sets the job back to idle.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from . import device_files, device_folder_access, device_state, tool_jobs
from .device_job_offers import (
    _ID,
    OfferChecks,
    Turn,
    offer_fields,
    slot_exempt,
)
from .device_job_run import TurnRunner
from .device_job_services import TurnServices
from .device_outbox import OutboxFullError
from .device_sdk import SdkDriver
from .device_session import PreparedSession, prepare_session
from .state import LocalState, read_json, write_private_json

logger = logging.getLogger("octryx_claude.device")

SEEN_FILE = "device-turns.json"
REASON_RESTARTED = "device_restarted"
RUNNING_FILE = "device-running.json"
REASON_SERVICE_RESTARTED = "service_restarted"
MAX_SEEN = 500
STOP_GRACE_SECONDS = 10.0


class JobManager(OfferChecks, TurnRunner, TurnServices):
    def __init__(self, state: LocalState, *, driver_factory: Callable[[], Any] = SdkDriver,
                 prepare: Callable[..., PreparedSession] = prepare_session,
                 http_factory: Callable[[], httpx.Client] = httpx.Client, shim: Path | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.state = state
        self.driver_factory = driver_factory
        self.prepare = prepare
        self.http_factory = http_factory
        self.shim = shim
        self.clock = clock
        self.channel: Any = None
        self.turns: dict[str, Turn] = {}
        self.draining = False  # set when the service restarts for an update: new turns are rejected
        self._approvals: dict[str, tuple[str, asyncio.Future]] = {}
        self._file_tasks: set[asyncio.Task] = set()
        self._route_tasks: set[asyncio.Task] = set()
        self.local_model: Any = None  # the local decision model (``router``), only when switched on
        self._seen: list[str] = list(read_json(state.root / SEEN_FILE).get("turns") or [])
        # The turns an earlier process of this service saw (read at start): a redelivery of one of them that this
        # process never ran was lost in a restart between offer and acceptance.
        self._seen_before = frozenset(self._seen)
        # Turns a previous run of the service left unfinished; reported once connected.
        stored = read_json(state.root / RUNNING_FILE).get("turns")
        self._orphans: dict[str, str] = {
            str(job): str(turn) for job, turn in (stored.items() if isinstance(stored, dict) else ())
            if _ID.match(str(job)) and _ID.match(str(turn))}
        self._save_running()

    def attach(self, channel: Any) -> None:
        self.channel = channel

    # --- platform messages ------------------------------------------------------------------------------------

    def _save_running(self) -> None:
        running = {**self._orphans, **{job_id: turn.turn_id for job_id, turn in self.turns.items()}}
        write_private_json(self.state.root / RUNNING_FILE, {"turns": running})

    async def report_orphans(self) -> None:
        """The previous run's unfinished turns end as failed (``service_restarted``); then they are forgotten."""
        for job_id, turn_id in list(self._orphans.items()):
            try:
                await self._send(job_id, "turn_finished", {"turn_id": turn_id, "status": "failed",
                                                           "reason": REASON_SERVICE_RESTARTED})
            except OutboxFullError:
                logger.error("job %s: the restart report did not fit the event buffer", job_id)
            self._orphans.pop(job_id, None)
            logger.info("job %s turn %s ended by the service restart", job_id, turn_id)
        self._save_running()

    async def handle(self, message_type: str, body: dict[str, Any]) -> None:
        if message_type == "connected":
            await self.report_orphans()
        elif message_type == "job_offer":
            await self._offer(body)
        elif message_type == "cancel":
            turn = self.turns.get(str(body.get("job_id") or ""))
            if turn is not None and turn.turn_id == str(body.get("turn_id") or turn.turn_id):
                await self.stop(turn, "stopped")
        elif message_type == "approval_decision":
            pending = self._approvals.get(str(body.get("approval_id") or ""))
            if pending is not None and pending[0] == str(body.get("job_id") or "") and not pending[1].done():
                pending[1].set_result(str(body.get("decision") or "denied"))
        elif message_type == "pause":
            await self.stop_all("paused")
        elif message_type == tool_jobs.MESSAGE_OFFER and self.channel is not None:
            # Pinned tools on code the platform sent, no agent (``tool_jobs``); off the receive loop.
            task = asyncio.create_task(tool_jobs.serve(self.state, body, self.channel.send_message))
            self._file_tasks.add(task)
            task.add_done_callback(self._file_tasks.discard)
        elif message_type == "file_request" and self.channel is not None:
            # A file a phone turn made here, asked for by the person (``device_files``); off the receive loop.
            server = device_files.FileServer(self.state, self.channel.send_message)
            task = asyncio.create_task(server.serve(body))
            self._file_tasks.add(task)
            task.add_done_callback(self._file_tasks.discard)

    def _remember(self, turn_id: str) -> bool:
        """``False`` when the turn was seen before (a redelivery after a reconnect or restart)."""
        if turn_id in self._seen:
            return False
        self._seen = [*self._seen, turn_id][-MAX_SEEN:]
        write_private_json(self.state.root / SEEN_FILE, {"turns": self._seen})
        return True

    async def _offer(self, body: dict[str, Any]) -> None:
        job_id, turn_id = str(body.get("job_id") or ""), str(body.get("turn_id") or "")
        if not _ID.match(job_id) or not _ID.match(turn_id):
            return
        if not self._remember(turn_id):
            if turn_id in self._seen_before and job_id not in self.turns:
                # Seen by an earlier process of this service that ended before it accepted the turn (a restart between
                # offer and acceptance): handed back, so it is not silent until the platform's 10-minute stall. The
                # platform offers it once more after a short wait.
                await self._send(job_id, "job_rejected", {"turn_id": turn_id, "reason": REASON_RESTARTED})
            return
        await self._after_clean_up(job_id)
        device = device_state.load_device(self.state)
        reason, folder = self._rejection(body, device)
        if reason:
            rejected = {"turn_id": turn_id, "reason": reason}
            if reason == device_folder_access.REASON_NOT_ACCESSIBLE:
                # The chat names the interpreter to allow in macOS Privacy & Security.
                rejected.update(os=str(device.get("os") or ""), service_python=device_folder_access.service_python())
            await self._send(job_id, "job_rejected", rejected)
            return
        turn = Turn(job_id, turn_id, limits=body.get("limits") if isinstance(body.get("limits"), dict) else {})
        turn.slot_exempt = slot_exempt(body)
        self.turns[job_id] = turn
        offer = offer_fields(body, folder, device, job_id)
        turn.task = asyncio.create_task(self._run(turn, offer))
        self._save_running()
        self._status()

    async def _send(self, job_id: str, message_type: str, body: dict[str, Any]) -> None:
        await self.channel.send_job(job_id, message_type, body)

    def _status(self) -> None:
        current = device_state.read_status(self.state)
        current["running_jobs"] = len(self.turns)
        device_state.write_status(self.state, current)

    # --- stopping ---------------------------------------------------------------------------------------------

    async def _interrupt(self, turn: Turn) -> None:
        if turn.driver is None:
            return
        with contextlib.suppress(Exception):
            await turn.driver.interrupt()

    async def stop(self, turn: Turn, reason: str) -> None:
        """Interrupt the turn; if it has not ended after the grace, end the Claude Code process."""
        turn.stop_reason = reason
        for approval_id, (job_id, future) in list(self._approvals.items()):
            if job_id == turn.job_id and not future.done():
                future.set_result("denied")
        await self._interrupt(turn)
        task = turn.task
        if task is None or task.done():
            return
        done, _ = await asyncio.wait({task}, timeout=STOP_GRACE_SECONDS)
        if not done and turn.driver is not None:
            with contextlib.suppress(Exception):
                await turn.driver.disconnect()

    async def stop_all(self, reason: str) -> None:
        await asyncio.gather(*(self.stop(turn, reason) for turn in list(self.turns.values())),
                             return_exceptions=True)


__all__ = [
    "JobManager",
]
