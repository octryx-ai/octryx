"""The story session of epic-delivery run exactly as plain Claude Code: ``claude -p``.

The turn runs as ``claude -p`` does (its command line and environment: ``plain_session``), not as an Agent SDK
session: streaming input with partial messages, background tasks off and extra MCP tools in the context made the
same story several times slower and more expensive.

- the platform's part is the session's settings file: its hooks decide every tool call on the device (the hard-deny
  list, ``local_decisions``), its deny rules hold in bypass mode too;
- the turn reports its session and its final answer; the live view reads the session's transcript.

Approvals cannot be asked in ``-p`` mode: this driver runs only bypass turns of a plain story session, whose hooks
decide alone.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from . import turn_idle
from .device_sdk_events import _clip
from .plain_session import (
    command,
    environment,
    map_line,
    own_request_shape,
    pin_subagent_models,
)
from .seat_status import turn_limit_code

# A child of the device service's logger: its lines land in the device log (the replay's lines under
# ``octryx_claude.plain_driver`` had no handler and never showed up).
logger = logging.getLogger("octryx_claude.device.plain")

STREAM_LIMIT = 64 * 1024 * 1024  # one stream-json line carries a whole tool result (a screenshot as base64)
TERMINATE_GRACE = 10.0
HEARTBEAT_SECONDS = 60.0
MAX_STOP_CONTINUATIONS = 5  # as the Codex turn (``codex_driver``); the platform's stall rule pauses sooner


class PlainCliDriver:
    """Runs one turn as ``claude -p``; ``interrupt``/``disconnect`` end the process."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._only_waiting: Path | None = None  # the transcript, when the launcher ended a process idle on a wakeup

    async def run_turn(self, prepared: Any, *, cwd: str, prompt: str, resume: str | None, fork: bool = False,
                       decide: Any = None, emit: Any) -> dict[str, Any]:
        """One turn: ``claude -p`` until it ends, then the platform's judgement of its last Stop (``replay_stop``).
        When the platform says "block", the same session goes on with the platform's reason, as an interactive
        session does at its Stop and as the Codex turn does (``codex_driver``): the agent sees what the platform
        found instead of ending the turn on its own "all green"."""
        result: dict[str, Any] = {}
        try:
            for _round in range(MAX_STOP_CONTINUATIONS + 1):
                result = await self._run_process(prepared, cwd=cwd, prompt=prompt, resume=resume, emit=emit)
                answer = await asyncio.to_thread(replay_stop, prepared, cwd)
                reason = str((answer or {}).get("reason") or "").strip()
                if result.get("status") != "success" or (answer or {}).get("decision") != "block" or not reason \
                        or not result.get("claude_session_id"):
                    break
                await emit({"kind": "text", "text": _clip(f"Octryx: {reason}", 2000)})
                prompt, resume = reason, str(result["claude_session_id"])
        finally:
            # The session ends once, after its last process (the seat credential lives until then).
            await asyncio.to_thread(replay_session_end, prepared, cwd)
        return result

    async def _run_process(self, prepared: Any, *, cwd: str, prompt: str, resume: str | None,
                           emit: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "error", "result_text": "", "claude_session_id": resume}
        self._only_waiting = None
        own_request_shape(prepared)
        pin_subagent_models(prepared)
        session = resume or prepared.session_key
        started = time.time()
        self._process = await asyncio.create_subprocess_exec(
            *command(prepared, resume=resume), cwd=cwd, env=environment(prepared),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=STREAM_LIMIT)
        beat = asyncio.create_task(self._heartbeat(emit, session))
        watch = asyncio.create_task(self._end_when_only_waiting(prepared, started))
        try:
            stdout, _ = await self._process.communicate(prompt.encode("utf-8"))
            try:
                row = json.loads(stdout or b"{}")
            except ValueError:
                row = {}
            rows = row if isinstance(row, list) else [row]
            for item in rows:
                if not isinstance(item, dict):
                    continue
                for event in map_line(item):
                    await emit(event)
                limit = turn_limit_code(item.get("error"))
                if limit and item.get("type") in ("assistant", "result"):
                    result["error"] = limit  # Claude Code's own error kind: the seat's limit
                if item.get("type") == "result" or "total_cost_usd" in item:
                    if item.get("session_id"):
                        await emit({"kind": "session", "claude_session_id": str(item["session_id"])})
                    if item.get("result"):
                        await emit({"kind": "text", "text": _clip(str(item["result"]), 16000)})
                    # ``total_cost_usd`` is the session's running total (restored on resume), information only:
                    # the platform prices the turn's transcript usage (``transcript_usage``).
                    result.update({"status": "error" if item.get("is_error") else "success",
                                   "result_text": str(item.get("result") or ""),
                                   "cost_usd": item.get("total_cost_usd"), "usage": item.get("usage"),
                                   "claude_session_id": item.get("session_id") or result["claude_session_id"]})
            if self._only_waiting is not None:
                await self._finished_while_waiting(result, started, session, emit)
        finally:
            beat.cancel()
            watch.cancel()
            await self.disconnect()
        return result

    @staticmethod
    async def _heartbeat(emit: Any, session: str) -> None:
        """The json output says nothing until the turn ends; the platform ends a turn that is silent for 10 minutes
        (``job_recovery``) even while the session works. The session event, repeated, keeps the turn alive and names
        the session it runs in."""
        while True:
            await emit({"kind": "session", "claude_session_id": session})
            await asyncio.sleep(HEARTBEAT_SECONDS)

    async def _end_when_only_waiting(self, prepared: Any, started: float) -> None:
        """End the process once its session has stopped and only a pending wakeup keeps it alive (``turn_idle``)."""
        stop_file = deferred_stop_path(prepared)
        if stop_file is None:
            return
        while self._process is not None and self._process.returncode is None:
            await asyncio.sleep(turn_idle.POLL_SECONDS)
            transcript = await asyncio.to_thread(turn_idle.only_waiting, stop_file, started, time.time())
            if transcript is not None and self._process is not None and self._process.returncode is None:
                logger.info("plain turn: the session stopped with no background task left; ending its wait")
                self._only_waiting = transcript
                with contextlib.suppress(ProcessLookupError):
                    self._process.terminate()
                return

    async def _finished_while_waiting(self, result: dict[str, Any], started: float, session: str,
                                      emit: Any) -> None:
        """The turn's work was done at its Stop: a success, with the session's last answer as its result."""
        if not result.get("result_text") and self._only_waiting is not None:
            text = await asyncio.to_thread(turn_idle.last_text, self._only_waiting, started)
            if text:
                await emit({"kind": "text", "text": _clip(text, 16000)})
            result["result_text"] = text
        stopped = await asyncio.to_thread(turn_idle.stopped_agents, self._only_waiting, started) \
            if self._only_waiting is not None else set()
        if stopped:  # said plainly, so the next turn carries on deliberately
            note = turn_idle.STOPPED_AGENT_NOTE.format(agents=", ".join(sorted(stopped)))
            await emit({"kind": "text", "text": note})
            result["result_text"] = f"{result.get('result_text') or ''}\n\n{note}".strip()
        result["status"] = "success"
        result["claude_session_id"] = result.get("claude_session_id") or session

    async def interrupt(self) -> None:
        if self._process is not None and self._process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._process.terminate()

    async def disconnect(self) -> None:
        process, self._process = self._process, None
        if process is None or process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), TERMINATE_GRACE)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.kill(process.pid, 9)


def deferred_stop_path(prepared: Any) -> Path | None:
    """Where the session's hook remembers its last Stop (``hooks._defer_stop``)."""
    from .hooks import DEFERRED_STOP_FILE  # noqa: PLC0415

    home = prepared.env.get("OCTRYX_CLAUDE_HOME") or ""
    return Path(home) / "sessions" / prepared.session_key / DEFERRED_STOP_FILE if home else None


def replay_stop(prepared: Any, cwd: str) -> dict[str, Any] | None:
    """The session's last deferred Stop (``hooks._defer_stop``), judged once the process ended: the launcher's own Stop
    hook with that input, so the platform's verification, screenshots and run contract work as in any turn. Returns
    the hook's answer (``{"decision": "block", "reason": ...}`` when the platform wants the agent to go on).

    A replay the platform did not judge (no answer, a timeout, "verification gate unreachable" for a 401, 5xx or a
    timeout, or a failed hook) runs once more after :data:`REPLAY_RETRY_SECONDS` with a fresh token, so an unjudged
    replay does not pause the phase ``phase_not_finished``."""
    from .hooks import DEFER_STOP_ENV  # noqa: PLC0415
    from .tokens import FORCE_REFRESH_ENV  # noqa: PLC0415

    stop_file = deferred_stop_path(prepared)
    path = str(stop_file) if stop_file is not None else ""
    if not path or not os.path.isfile(path):
        return None
    shim = str(prepared.extra.get("hook_shim") or prepared.env.get("OCTRYX_TEST_RUN_SHIM") or "")
    if not shim:
        return None
    env = {key: value for key, value in prepared.env.items() if key != DEFER_STOP_ENV}
    # Claude Code gives its own hooks the project folder; this replay runs outside it. Without it the hook would take
    # the agent's last cwd (possibly a subfolder) as the repository root, the repository-relative changed files would
    # not resolve under it and no formatter would run at the Stop.
    env.setdefault("CLAUDE_PROJECT_DIR", cwd)
    with open(path, "rb") as handle:
        data = handle.read()
    answer, judged = _run_stop_hook(shim, data, cwd, env)
    if not judged:
        logger.info("stop replay: not judged (%s); once more with a fresh token", _describe(answer))
        time.sleep(REPLAY_RETRY_SECONDS)
        answer, judged = _run_stop_hook(shim, data, cwd, {**env, FORCE_REFRESH_ENV: "1"})
    logger.info("stop replay: %s", "judged" if judged else f"not judged ({_describe(answer)})")
    with contextlib.suppress(OSError):
        os.unlink(path)
    return answer


def replay_session_end(prepared: Any, cwd: str) -> bool:
    """The session's last deferred SessionEnd (``hooks.DEFER_SESSION_END_ENV``), run once the turn is over: the
    launcher's own SessionEnd hook with that input (finalize, digest, lessons). ``True`` when one was replayed."""
    from .hooks import DEFER_STOP_ENV
    from .session_hooks import (
        DEFER_SESSION_END_ENV,
        DEFERRED_SESSION_END_FILE,  # noqa: PLC0415
    )

    home = prepared.env.get("OCTRYX_CLAUDE_HOME") or ""
    path = Path(home) / "sessions" / prepared.session_key / DEFERRED_SESSION_END_FILE if home else None
    shim = str(prepared.extra.get("hook_shim") or prepared.env.get("OCTRYX_TEST_RUN_SHIM") or "")
    if path is None or not path.is_file() or not shim:
        return False
    env = {key: value for key, value in prepared.env.items() if key not in (DEFER_STOP_ENV, DEFER_SESSION_END_ENV)}
    env.setdefault("CLAUDE_PROJECT_DIR", cwd)
    import subprocess  # noqa: PLC0415

    try:
        subprocess.run([shim, "hook", "session-end"], input=path.read_bytes(), cwd=cwd, env=env, capture_output=True,
                       timeout=REPLAY_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        logger.info("session end replay: the hook did not run")
    with contextlib.suppress(OSError):
        path.unlink()
    return True


REPLAY_RETRY_SECONDS = 5.0
REPLAY_TIMEOUT_SECONDS = 120
# The Stop hook's own answers when the platform did not judge the stop (``hooks.stop_output`` for an unreachable or
# refused verification, ``hooks.run_stop`` for a hook that failed).
_NOT_JUDGED = ("Octryx verification gate unreachable", "Octryx stop hook failed")


def _run_stop_hook(shim: str, data: bytes, cwd: str, env: dict[str, str]) -> tuple[dict[str, Any] | None, bool]:
    """The Stop hook's answer and whether the platform judged the stop."""
    import subprocess  # noqa: PLC0415

    try:
        done = subprocess.run([shim, "hook", "stop"], input=data, cwd=cwd, env=env, capture_output=True,
                              timeout=REPLAY_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, False
    if done.returncode != 0:
        return None, False
    try:
        parsed = json.loads(done.stdout or b"null")
    except ValueError:
        return None, False
    if parsed is None:
        return None, True  # passed: the hook prints nothing
    answer = parsed if isinstance(parsed, dict) else None
    message = str((answer or {}).get("systemMessage") or "")
    return answer, answer is not None and not message.startswith(_NOT_JUDGED)


def _describe(answer: dict[str, Any] | None) -> str:
    return str((answer or {}).get("systemMessage") or "no answer")[:160]


def runs_plain(prepared: Any) -> bool:
    """A bypass turn of a plain story session (epic-delivery); any other turn keeps the SDK driver."""
    from .device_turn_kind import plain_session  # noqa: PLC0415

    return plain_session(prepared) and prepared.extra.get("permission_mode") == "bypassPermissions"


__all__ = [
    "PlainCliDriver",
    "runs_plain",
]
