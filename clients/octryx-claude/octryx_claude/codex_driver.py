"""A device turn on OpenAI Codex CLI instead of Claude Code (Codex as the second engine).

The platform decides the engine (``agent_gateway/engine_policy``) and the job offer carries it. A Codex turn keeps
everything that makes an octryx session governed:

- **models only through the platform**: a per-session ``CODEX_HOME`` whose ``config.toml`` names one provider, the
  platform's OpenAI Responses gateway (``/api/v1/model-gateway/openai/v1``), with the session headers and the
  launcher's ``api-key-helper`` as its token command. No key is written anywhere; ``auth.json`` is never stored
  (``cli_auth_credentials_store = "ephemeral"``). Codex never sees a Claude seat;
- **the same hooks**: Codex's PreToolUse/PostToolUse/Stop hooks call the launcher's hook entry with Claude-compatible
  JSON (shell = ``Bash``, edits = ``apply_patch``), so the hard-deny list, the platform's decisions, the audit and the
  verification apply as in a Claude Code turn; the PreToolUse hook fails closed. The Stop hook is deferred and
  replayed once the process ended, like the plain ``claude -p`` story session (``plain_driver.replay_stop``);
- **the platform's MCP server** with the same ``mcp-headers`` helper (``http_headers_helper``);
- **one session per epic**: the Codex thread id is the turn's ``claude_session_id``, and the next turn continues it
  with ``codex exec resume <thread_id>``.

``codex exec --json`` streams JSON lines; they become the chat's job events (text, tool use and result, usage).
Approvals cannot be asked in exec mode: a turn whose permission mode is not ``bypassPermissions`` runs in Codex's
``workspace-write`` sandbox (writes only in the work folder), a bypass turn without Codex's sandbox, decided by the
hooks alone, like a Claude Code bypass turn.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .codex_config import (
    environment,
    prepare_home,
)
from .codex_events import map_line, rollout_rate_limits, usage_of
from .device_sdk import DriverStartError
from .device_sdk_events import _clip
from .seat_status import codex_limit_code

ENGINE = "codex"
CODEX_PATH_ENV = "OCTRYX_CODEX_PATH"
# 0.169.0: hooks run in ``codex exec`` with ``--dangerously-bypass-hook-trust``, MCP
# ``http_headers_helper`` and provider ``auth.command`` exist, and ``wire_api`` is ``responses`` only.
MIN_VERSION = (0, 169, 0)
STREAM_LIMIT = 64 * 1024 * 1024
TERMINATE_GRACE = 10.0
HEARTBEAT_SECONDS = 60.0
# How often a turn goes on in the same thread when the platform's Stop hook says it is not done (the hook caps its
# own blocks too; this is the driver's bound).
MAX_STOP_CONTINUATIONS = 5  # the gateway token lives longer; Codex asks again well before it ends
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class CodexUnavailableError(Exception):
    def __init__(self, code: str, *, path: str = "", found: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        self.found = found

    def hint(self) -> str:
        """``needs_configuration: <code> (...)`` with the minimum version, the found one and the update command
        for how Codex is installed (Homebrew or npm)."""
        wanted = ".".join(map(str, MIN_VERSION))
        command = update_command(self.path)
        if self.code == "codex_too_old":
            found = f" (found {self.found})" if self.found else ""
            return (f"needs_configuration: codex_too_old: Codex CLI {wanted} or newer is needed{found}; "
                    f"update with: {command}")
        return (f"needs_configuration: {self.code}: install Codex CLI {wanted} or newer ({command}), or set "
                f"{CODEX_PATH_ENV} to it")


def update_command(path: str) -> str:
    """How to update the Codex CLI at ``path``: Homebrew's, npm's, or both named when unknown."""
    real = os.path.realpath(path) if path else ""
    if "/Cellar/" in real or "/Caskroom/" in real or real.startswith(("/opt/homebrew/", "/home/linuxbrew/")):
        return "brew upgrade codex"
    if "node_modules" in real:
        return "npm install -g @openai/codex@latest"
    return "brew upgrade codex  or  npm install -g @openai/codex@latest"


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(text or "")
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def resolve_codex(environ: dict[str, str] | None = None) -> str:
    """The ``codex`` binary (``OCTRYX_CODEX_PATH`` first) at :data:`MIN_VERSION` or newer; raises
    :class:`CodexUnavailableError` (``codex_not_installed`` / ``codex_too_old``)."""
    env = os.environ if environ is None else environ
    path = env.get(CODEX_PATH_ENV) or shutil.which("codex", path=env.get("PATH")) or ""
    if not path or not os.access(path, os.X_OK):
        raise CodexUnavailableError("codex_not_installed")
    try:
        shown = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        raise CodexUnavailableError("codex_not_installed") from None
    version = parse_version(shown)
    if version is None or version < MIN_VERSION:
        raise CodexUnavailableError("codex_too_old", path=path,
                                    found=".".join(map(str, version)) if version else "unknown")
    return path


# --- the session's CODEX_HOME ----------------------------------------------------------------------------------


def command(codex: str, *, cwd: str, prompt: str, resume: str | None) -> list[str]:
    # ``--trust``: Codex 0.169 starts no MCP server in a folder it does not trust (the platform's
    # tools were missing); the trust is stored in the session's own CODEX_HOME only.
    head = [codex, "exec", "--json", "--trust", "--dangerously-bypass-hook-trust", "--skip-git-repo-check", "-C", cwd]
    if resume:
        return [*head, "resume", resume, prompt]
    return [*head, prompt]


# --- events ------------------------------------------------------------------------------------------------------


class CodexDriver:
    """Runs one turn as ``codex exec --json``; ``interrupt``/``disconnect`` end the process."""

    def __init__(self, codex_path: str | None = None, *, proxy_factory: Any = None) -> None:
        self._codex = codex_path
        self._process: asyncio.subprocess.Process | None = None
        self._proxy: Any = None
        # Builds the job's seat proxy (``codex_seat_proxy.SeatProxy``) from the platform URL; a seam for tests.
        self._proxy_factory = proxy_factory

    async def run_turn(self, prepared: Any, *, cwd: str, prompt: str, resume: str | None, fork: bool = False,
                       decide: Any = None, emit: Any) -> dict[str, Any]:
        if fork:
            raise DriverStartError("codex_fork_unsupported")
        try:
            codex = self._codex or await asyncio.to_thread(resolve_codex, prepared.env)
        except CodexUnavailableError as exc:
            raise DriverStartError(exc.code) from None
        sandboxed = prepared.extra.get("permission_mode") != "bypassPermissions"
        proxy = await self._start_proxy(prepared)
        try:
            home = await asyncio.to_thread(prepare_home, prepared, sandboxed=sandboxed,
                                           seat_proxy=proxy.url if proxy is not None else "")
            return await self._run_rounds(prepared, codex, home, cwd=cwd, prompt=prompt, resume=resume, emit=emit)
        finally:
            await self._stop_proxy()

    async def _start_proxy(self, prepared: Any) -> Any:
        """The job's loopback seat proxy when the seat's calls leave from this device (``seat_traffic: device``)."""
        from .codex_seat import sends_from_device  # noqa: PLC0415

        if not sends_from_device(prepared.extra):
            return None
        from .codex_seat_proxy import SeatProxy  # noqa: PLC0415

        base_url = str((prepared.extra.get("gateway") or {}).get("base_url") or "")
        try:
            self._proxy = await (self._proxy_factory or SeatProxy)(base_url).start()
        except OSError:
            raise DriverStartError("codex_seat_proxy_unavailable") from None
        return self._proxy

    async def _stop_proxy(self) -> None:
        proxy, self._proxy = self._proxy, None
        if proxy is not None:
            await proxy.stop()

    async def _run_rounds(self, prepared: Any, codex: str, home: Path, *, cwd: str, prompt: str, resume: str | None,
                          emit: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "error", "result_text": "", "claude_session_id": resume,
                                  "engine": ENGINE}
        usage: dict[str, int] = {}
        from .plain_driver import replay_stop  # noqa: PLC0415

        ok = False
        for _round in range(MAX_STOP_CONTINUATIONS + 1):
            ok = await self._run_once(prepared, codex, home, cwd=cwd, prompt=prompt, resume=resume, emit=emit,
                                      result=result, usage=usage)
            # The platform's Stop hook, judged once the process ended. Claude Code goes on in the same process when
            # it says "block" (e.g. the phase is not finished); Codex has ended, so the same thread continues with
            # the platform's reason (a spec interview ended after reading the repo and paused).
            answer = await asyncio.to_thread(replay_stop, prepared, cwd)
            reason = str((answer or {}).get("reason") or "").strip()
            if not ok or (answer or {}).get("decision") != "block" or not reason or not result["claude_session_id"]:
                break
            await emit({"kind": "text", "text": _clip(f"Octryx: {reason}", 2000)})
            prompt, resume = reason, str(result["claude_session_id"])
        if usage:
            result["usage"] = usage
        result["status"] = "success" if ok else "error"
        if prepared.extra.get("codex_seat") and result.get("claude_session_id"):
            limits = await asyncio.to_thread(rollout_rate_limits, home / "sessions", str(result["claude_session_id"]))
            if limits:
                result["seat_rate_limits"] = limits
        return result

    async def _run_once(self, prepared: Any, codex: str, home: Path, *, cwd: str, prompt: str, resume: str | None,
                        emit: Any, result: dict[str, Any], usage: dict[str, int]) -> bool:
        """One ``codex exec`` process; ``True`` when its turn completed without failure."""
        self._process = await asyncio.create_subprocess_exec(
            *command(codex, cwd=cwd, prompt=prompt, resume=resume), cwd=cwd,
            env=environment(prepared, home, proxy_token=self._proxy.token if self._proxy is not None else ""),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=STREAM_LIMIT)
        if resume:
            # ``codex exec resume`` keeps the thread id and may not report ``thread.started`` again: the turn names its
            # session at once, so the platform knows the job's session (and engine) for the epic's next story.
            await emit({"kind": "session", "claude_session_id": resume})
            result["claude_session_id"] = resume
        beat = asyncio.create_task(self._heartbeat(emit, result))
        completed = failed = False
        limit = ""
        code: int | None = None
        try:
            assert self._process.stdout is not None
            async for raw in self._process.stdout:
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                for event in map_line(row):
                    if event["kind"] == "session":
                        result["claude_session_id"] = event["claude_session_id"]
                    if event["kind"] == "text":
                        result["result_text"] = event["text"]
                    await emit(event)
                if row.get("type") == "turn.completed":
                    completed = True
                    for key, value in usage_of(row.get("usage")).items():
                        usage[key] = usage.get(key, 0) + value
                elif row.get("type") in ("turn.failed", "error"):
                    failed = True
                    limit = limit or codex_limit_code(row)
            await self._process.wait()
            code = self._process.returncode
        finally:
            beat.cancel()
            await self.disconnect()
        ok = completed and not failed and code == 0
        if not ok:
            # The ChatGPT seat's limit as a fixed code (``usage_limit`` / ``rate_limit``): the platform keeps the
            # run's Codex seat apart from its Claude seat and falls back by it.
            result["error"] = limit or ("codex_turn_failed" if failed else f"codex_exit_{code}")
        return ok

    @staticmethod
    async def _heartbeat(emit: Any, result: dict[str, Any]) -> None:
        """A long command prints nothing; the platform ends a turn that is silent for 10 minutes. The session event
        names the Codex thread once it is known (never the launcher's own key: the next turn resumes by it)."""
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            thread = result.get("claude_session_id")
            await emit({"kind": "session", "claude_session_id": thread} if thread else {"kind": "heartbeat"})

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


def runs_codex(offer: dict[str, Any]) -> bool:
    return str(offer.get("engine") or "") == ENGINE


__all__ = [
    "CodexDriver",
    "CodexUnavailableError",
    "resolve_codex",
    "runs_codex",
]
