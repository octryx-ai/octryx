"""One accepted device turn from start to end: prepare the session, pick the driver, run it, report what it used and
changed, and clean up after it (mixed into ``device_jobs.JobManager``)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import (
    device_files,
    device_service,
    device_state,
    engine_state,
    install_layout,
    token_profile,
    transcript_upload,
    transcript_usage,
    turn_processes,
    work_git,
)
from .codex_driver import CodexDriver, runs_codex
from .context_pack import with_context_pack
from .device_job_offers import LOCAL_PREFIX
from .device_outbox import OutboxFullError
from .device_sdk import DriverStartError, DriverUnavailableError
from .device_session import PreparedSession, SessionRefusedError, prepare_local
from .state import LocalState

if TYPE_CHECKING:
    from .device_job_offers import Turn

logger = logging.getLogger("octryx_claude.device")
CLEAN_UP_WAIT_SECONDS = 120.0
Emit = Callable[[dict[str, Any]], Awaitable[None]]


def notify_takeover(profile: str, folder: str) -> None:
    from .mac_notify import notify  # noqa: PLC0415 - shows as "Octryx", not "Script Editor"

    notify("Octryx", f"Your phone continues a Claude Code session ({profile}) in {os.path.basename(folder) or folder}")


def with_pipeline_red(state: LocalState, prepared: Any, prompt: str) -> str:
    from .pipeline import RED_FILE  # noqa: PLC0415

    key = getattr(prepared, "session_key", "")
    if not key or getattr(prepared, "extra", {}).get("local"):
        return prompt
    try:
        path = state.session_dir(key) / RED_FILE
        summary = path.read_text(encoding="utf-8") if path.is_file() else ""
    except (OSError, ValueError):
        return prompt
    if not summary:
        return prompt
    return f"{prompt}\n\n{summary}"  # the pipeline wrote the platform's header with it (run.launcher.pipeline_red)


def session_shim(executable: str | None = None) -> Path:
    # Settings and hooks of one session must come from the same code; ``current`` lets a self-update reach the
    # next hook call.
    checkout = install_layout.CHECKOUT_SHIM
    if checkout.is_file():
        return checkout
    own = Path(executable or sys.executable).parent / "octryx-claude"
    current = own.parent.parent.parent / "current" / "bin" / "octryx-claude"
    if own.parent.parent.parent.name == "venvs" and current.is_file():
        return current
    return own if own.is_file() else device_service.service_shim()


async def extend_prepared(state: LocalState, prepared: PreparedSession, offer: dict[str, Any]) -> None:
    if offer.get("browser") is True and offer.get("workflow_run"):
        from . import browser_mcp  # noqa: PLC0415

        # Installed once (pinned) into the state folder; ``None`` leaves the turn without a browser. Every
        # engine of a run turn whose phase opted in: the SDK session, plain ``claude -p`` (epic-delivery)
        # and Codex.
        prepared.extra["browser_mcp"] = await asyncio.to_thread(
            browser_mcp.server_spec, state.root, prepared.session_key,
            platform_url=str(offer.get("base_url") or ""),
            external=offer.get("browser_external") is True)
    prepared.extra.update(permission_mode=offer.get("permission_mode") or "",
                          effort=offer.get("effort") or "",
                          # A workflow run's own turn starts lean (base context < 10k),
                          # and so does any turn the server marks lean (governed models).
                          lean=bool(offer.get("workflow_run")) or offer.get("lean") is True,
                          workflow_run=bool(offer.get("workflow_run")),
                          subagents=offer.get("subagents") is True,
                          model_context_window=int(offer.get("model_context_window") or 0),
                          # The run turn's built-in tools and prompt texts (data).
                          builtin_tools=list(offer.get("builtin_tools") or []),
                          system_prompt=str(offer.get("system_prompt") or ""),
                          story_prompt=str(offer.get("story_prompt") or ""),
                          plain_prompt=str(offer.get("plain_prompt") or ""),
                          # The run class's context cap: Claude Code compacts there itself.
                          compact_window=offer.get("compact_window"),
                          web=offer.get("web") is True,
                          browser_external=offer.get("browser_external") is True,
                          # epic-delivery: plain Claude Code (its settings, a short run note).
                          plain=isinstance(offer.get("local_decisions"), dict),
                          context_window=device_state.context_window(device_state.load_device(state)))
    # The hooks' browser rule reads it like the platform's URL (``run_shell.browser_rule``).
    from .browser_rules import BROWSER_EXTERNAL_ENV  # noqa: PLC0415

    prepared.env.pop(BROWSER_EXTERNAL_ENV, None)
    if offer.get("browser_external") is True:
        prepared.env[BROWSER_EXTERNAL_ENV] = "1"


class TurnRunner:
    async def _after_clean_up(self, job_id: str) -> None:
        # The platform offers the next turn on turn_finished while clean-up may still run; refusing it would pause
        # the run.
        turn = self.turns.get(job_id)
        if turn is None or not turn.finished or turn.task is None or turn.task.done():
            return
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(asyncio.shield(turn.task), CLEAN_UP_WAIT_SECONDS)

    def _prepare(self, offer: dict[str, Any]) -> PreparedSession:
        if offer["profile"].startswith(LOCAL_PREFIX):
            return prepare_local(self.state, offer["profile"][len(LOCAL_PREFIX):])
        with self.http_factory() as http:
            return self.prepare(self.state, base_url=offer["base_url"], workspace_id=offer["workspace_id"],
                                profile=offer["profile"], folder=offer["folder"], model=offer["model"], http=http,
                                workflow_run=offer.get("workflow_run", ""), job_id=offer.get("job_id", ""),
                                shim=self.shim or session_shim(), **({"engine": "codex"} if runs_codex(offer) else {}))

    def _pick_driver(self, offer: dict[str, Any], prepared: PreparedSession) -> Any:
        from .pi_driver import PiDriver, chosen_harness, uses_pi

        # A device may run its governed chat turns on pi instead of Claude Code.
        from .plain_driver import PlainCliDriver, runs_plain
        from .review_call import ReviewCallDriver, runs_review

        # The platform chose Codex for this job (``codex_driver``).
        return (ReviewCallDriver(self._review_control(offer, prepared), engine="codex" if runs_codex(offer) else "")
                if runs_review(offer) else
                CodexDriver(prepared.cli_path) if runs_codex(offer) else
                PiDriver(self.state.root, chosen_harness(self.state.root))
                if uses_pi(self.state.root, offer) else
                # epic-delivery: the story session runs as ``claude -p``, like plain Claude Code.
                PlainCliDriver() if runs_plain(prepared) else self.driver_factory())

    def _emitter(self, turn: Turn) -> Emit:
        async def emit(event: dict[str, Any]) -> None:
            await self._send(turn.job_id, "job_event", {"turn_id": turn.turn_id, **event})

        return emit

    async def _run(self, turn: Turn, offer: dict[str, Any]) -> None:
        prepared: PreparedSession | None = None
        uploads: transcript_upload.Running | None = None
        emit = self._emitter(turn)
        try:
            try:
                prepared = await asyncio.to_thread(self._prepare, offer)
                await extend_prepared(self.state, prepared, offer)
                turn.driver = self._pick_driver(offer, prepared)
            except (SessionRefusedError, DriverUnavailableError) as exc:
                await self._send(turn.job_id, "job_rejected", {"turn_id": turn.turn_id, "reason": exc.code})
                return
            started = time.time()
            await asyncio.to_thread(device_files.remember_turn, self.state, turn.job_id, offer["folder"], started)
            await self._send(turn.job_id, "job_accepted", {"turn_id": turn.turn_id})
            if offer["profile"].startswith(LOCAL_PREFIX):  # the Mac sees every remote turn
                notify_takeover(offer["profile"][len(LOCAL_PREFIX):], offer["folder"])
            self._suggest_route(offer, emit)  # measured alongside, never waited for
            await engine_state.before_turn(self.state, prepared, offer, job_id=turn.job_id)
            # The turn's full transcript, only when the Workspace switched it on.
            uploads = transcript_upload.start_for_turn(prepared, offer)
            result = await self._drive(turn, offer, prepared, emit)
            if uploads is not None and result.get("claude_session_id"):
                uploads.bind(str(result["claude_session_id"]))  # a forked turn writes under its own new id
            if turn.stop_reason:
                result["status"] = turn.stop_reason
            await self._report_usage(prepared, offer, result, started, emit)
            await self._report_work(prepared, offer, started, emit)
            await engine_state.after_turn(self.state, prepared, offer, result, job_id=turn.job_id,
                                          turn_id=turn.turn_id)
            turn.finished = True
            await self._send(turn.job_id, "turn_finished", {"turn_id": turn.turn_id, **result})
        except OutboxFullError:
            logger.error("job %s stopped: event buffer full", turn.job_id)
            await self._interrupt(turn)
        except Exception as exc:  # noqa: BLE001 - a failed turn is reported, never crashes the service
            logger.exception("job %s failed", turn.job_id)
            turn.finished = True
            with contextlib.suppress(OutboxFullError):
                await self._send(turn.job_id, "turn_finished", {"turn_id": turn.turn_id, "status": "error",
                                                                "error": type(exc).__name__})
        finally:
            await self._end_turn(turn, prepared, uploads, emit)

    async def _drive(self, turn: Turn, offer: dict[str, Any], prepared: PreparedSession, emit: Emit) -> dict:

        async def decide(tool: str, tool_input: dict[str, Any]) -> tuple[str, str]:
            return await self._decide(turn, tool, tool_input)

        if turn.stop_reason:
            return {"status": turn.stop_reason}

        uploader = self._start_audit_upload(prepared, offer)
        offer["prompt"] = with_pipeline_red(self.state, prepared, offer["prompt"])
        offer["prompt"], pack = await asyncio.to_thread(with_context_pack, self.state.root, offer, prepared.session_key)
        if pack is not None:
            await emit(pack)
        if offer.get("workflow_run"):
            # Every process of the run turn carries this mark; what still listens after it is stopped below.
            prepared.env[turn_processes.MARK_ENV] = turn_processes.new_mark()
        try:
            result = await asyncio.wait_for(
                turn.driver.run_turn(prepared, cwd=offer["folder"], prompt=offer["prompt"],
                                     resume=offer["resume"], fork=offer.get("fork", False), decide=decide,
                                     emit=emit),
                timeout=turn.max_job_minutes * 60)
        except TimeoutError:
            turn.stop_reason = "timed_out"
            await self._interrupt(turn)
            result = {"status": "timed_out"}
        except DriverStartError as exc:
            logger.error("job %s: Claude Code did not start: %s", turn.job_id, exc.code)
            result = {"status": "error", "error": exc.code}
        finally:
            if uploader is not None:
                uploader.cancel()
                await asyncio.to_thread(self._drain_audit, prepared, offer)  # what the Stop hook did not send
        return result

    async def _report_usage(self, prepared: PreparedSession | None, offer: dict[str, Any], result: dict,
                            started: float, emit: Emit) -> None:
        if prepared is None:
            return
        # The platform prices what the turn used, read from its transcript per model, subagents included
        # (``transcript_usage``): also when no result was printed (wakeup wait, crash, kill, timeout), and
        # also when one was, as Claude Code's ``total_cost_usd`` is the session's running total.
        usage = await asyncio.to_thread(transcript_usage.for_turn, prepared, offer, result, started)
        if usage is not None:
            result["usage"] = usage
        # Where the tokens went (``token_profile``): per call and per tool result, for the run's Tokens view.
        streams = transcript_usage.turn_streams(prepared, offer, result)
        profile = await asyncio.to_thread(token_profile.turn_profile, streams, started) if streams else None
        for event in token_profile.events(profile) if profile else []:
            await emit(event)

    async def _report_work(self, prepared: PreparedSession, offer: dict[str, Any], started: float,
                           emit: Emit) -> None:
        if offer.get("workflow_run") and not work_git.is_item_folder(offer["folder"]):
            # The run's work in progress travels with it (``run_wip``); an item's worktree is merged instead.
            from .run_wip import push_run_wip

            wip = await asyncio.to_thread(push_run_wip, offer["folder"], offer["workflow_run"],
                                          str((getattr(prepared, "extra", None) or {}).get("commit_trailer") or ""))
            await emit({"kind": "wip_pushed" if wip["state"] in ("pushed", "unchanged") else "wip_failed",
                        **wip})
        # The files this turn changed, by name only: the person opens one from the app on demand.
        files = await asyncio.to_thread(device_files.changed_files, offer["folder"], started - 2,
                                        state_root=self.state.root)
        if files:
            await emit({"kind": "files", "files": files})

    async def _end_turn(self, turn: Turn, prepared: PreparedSession | None,
                        uploads: transcript_upload.Running | None, emit: Emit) -> None:
        if uploads is not None:
            await asyncio.to_thread(uploads.stop)  # what is left goes once, off the event loop
        if prepared is not None:
            mark = turn_processes.mark_of(prepared.env)
            if mark:
                ended: list[dict] = []
                stopped = await asyncio.to_thread(turn_processes.stop_leftovers, mark, record=ended.append)
                if stopped:
                    logger.info("job %s: stopped %d app server(s) the turn left running", turn.job_id,
                                len(stopped))
                    with contextlib.suppress(Exception):  # the record never fails the turn's end
                        await emit({"kind": "leftovers_stopped", "processes": ended[:20]})
            prepared.close()
        self.turns.pop(turn.job_id, None)
        self._save_running()
        self._status()
