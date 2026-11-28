"""A device turn on OpenAI Codex (``codex app-server``): it starts only with the launcher's own hooks, settings and
platform tools in effect (``codex_trust``), and its approvals go to the chat."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import codex_trust
from .codex_appserver import EXITED, AppServerClient, AppServerError, UnknownServerRequestError
from .codex_config import (
    CONFIG_APPROVAL,
    ENV_WRAPPER,
    container_boundary,
    environment,
    guard_command,
    hook_declarations,
    hook_path,
    prepare_home,
    shell_environment,
    thread_approval,
)
from .codex_events import context_of, limit_code, map_hook, map_item, rollout_rate_limits, usage_of
from .codex_hook_input import CODEX_MCP_SERVER
from .device_sdk import DriverStartError
from .device_sdk_events import _clip
from .runner import agent_command

ENGINE = "codex"
CODEX_PATH_ENV = "OCTRYX_CODEX_PATH"
# 0.169.0: app-server ``hooks/list`` with hook trust, MCP ``http_headers_helper`` and provider ``auth.command``.
MIN_VERSION = (0, 169, 0)
HEARTBEAT_SECONDS = 60.0
TURN_TIMEOUT = 6 * 60 * 60.0
COMPACT_PROMPT = "/compact"
INTERRUPT_TIMEOUT = 10.0
MCP_READY_SECONDS = 10.0
MCP_READY_POLL_SECONDS = 0.25
_SANDBOX_TYPES = {"workspace-write": "workspaceWrite", "danger-full-access": "dangerFullAccess"}
_ANSWER_PHASES = (None, "final_answer")
_HTTP_STATUS = re.compile(r"HTTP[^0-9\n]{0,40}\b([45]\d\d)\b")
_MCP_STATES = ("notStarted", "starting", "connected", "authenticationRequired", "failed", "cancelled", "disabled")
_TURN_STATES = ("completed", "interrupted", "failed")
# The platform's verification states that let a turn end (needs_configuration: not set up; the turn is not held).
_STOP_PASSED = ("passed", "not_applicable", "needs_configuration")
_ERROR_KINDS = ("contextWindowExceeded", "sessionBudgetExceeded", "usageLimitExceeded", "rateLimitExceeded",
                "flexUnavailable", "serverOverloaded", "modelNotFound", "policyCapacityUnavailable", "cyberPolicy",
                "misalignmentPolicyViolation", "tooManyDenials", "internalServerError", "unauthorized", "badRequest",
                "threadRollbackFailed", "sandboxError", "inferenceHookDenied", "httpConnectionFailed",
                "responseStreamConnectionFailed")
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
        wanted = ".".join(map(str, MIN_VERSION))
        command = update_command(self.path)
        if self.code == "codex_too_old":
            found = f" (found {self.found})" if self.found else ""
            return (f"needs_configuration: codex_too_old: Codex CLI {wanted} or newer is needed{found}; "
                    f"update with: {command}")
        return (f"needs_configuration: {self.code}: install Codex CLI {wanted} or newer ({command}), or set "
                f"{CODEX_PATH_ENV} to it")


def update_command(path: str) -> str:
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


class CodexStoppedError(Exception):
    pass


class CodexDriver:
    def __init__(self, codex_path: str | None = None) -> None:
        self._codex = codex_path
        self._client: AppServerClient | None = None
        self._decide: Any = None
        self._stopped = False
        self._thread = ""
        self._turn = ""
        self._wrapper = ""
        self._chain: list[Path] = []
        self._chain_files: list[Path] = []
        self._chain_hashes: dict[str, str] = {}

    async def run_turn(self, prepared: Any, *, cwd: str, prompt: str, resume: str | None, fork: bool = False,
                       decide: Any = None, emit: Any) -> dict[str, Any]:
        if fork:
            raise DriverStartError("codex_fork_unsupported")
        try:
            codex = self._codex or await asyncio.to_thread(resolve_codex, prepared.env)
        except CodexUnavailableError as exc:
            raise DriverStartError(exc.code) from None
        self._decide = decide
        result: dict[str, Any] = {"status": "error", "result_text": "", "claude_session_id": resume, "engine": ENGINE}
        usage: dict[str, int] = {}
        home: Path | None = None
        beat = asyncio.create_task(self._heartbeat(emit, result))
        try:
            self._check_stop()
            sandbox = self._sandbox(prepared)
            home = await asyncio.to_thread(prepare_home, prepared, sandboxed=sandbox == "workspace-write",
                                           device_turn=True)
            folders = await asyncio.to_thread(codex_trust.repository_folders, cwd)
            await asyncio.to_thread(codex_trust.untrust_folders, home / "config.toml", folders)
            self._wrapper = str(home / ENV_WRAPPER)
            # What the launcher wrote is checked again before every round: the Stop's replay runs repository
            # tools outside Codex's sandbox.
            from . import codex_hook_guard  # noqa: PLC0415

            self._chain_files = [home / "config.toml", home / ENV_WRAPPER, Path(codex_hook_guard.__file__)]
            self._chain_hashes = await asyncio.to_thread(codex_trust.content_hashes, self._chain_files)
            self._chain = hook_chain(home, prepared)
            await self._preflight(home, cwd=cwd, sandbox=sandbox, emit=emit)
            await self._open(codex, prepared, home, cwd=cwd, resume=resume, sandbox=sandbox, emit=emit)
            result["claude_session_id"] = self._thread
            await emit({"kind": "session", "claude_session_id": self._thread})
            if prompt.strip() == COMPACT_PROMPT:  # as in Claude Code: the thread's context is compacted
                ok = await self._compact(emit=emit, result=result, usage=usage)
            else:
                ok = await self._rounds(prepared, cwd=cwd, prompt=prompt, emit=emit, result=result, usage=usage)
        except AppServerError as exc:
            result["error"] = f"codex_app_server_{exc.method.replace('/', '_')}"
            ok = False
        except CodexStoppedError:
            result["error"] = "codex_stopped"
            ok = False
        finally:
            beat.cancel()
            await self.disconnect()
        if usage:
            result["usage"] = usage
        result["status"] = "success" if ok else "error"
        if prepared.extra.get("codex_seat") and self._thread and home is not None:
            limits = await asyncio.to_thread(rollout_rate_limits, home / "sessions", self._thread)
            if limits:
                result["seat_rate_limits"] = limits
        return result

    @staticmethod
    def _sandbox(prepared: Any) -> str:
        sandboxed = prepared.extra.get("permission_mode") != "bypassPermissions"
        return "workspace-write" if sandboxed and not container_boundary(prepared) else "danger-full-access"

    def _check_stop(self) -> None:
        if self._stopped:
            raise CodexStoppedError

    async def _open(self, codex: str, prepared: Any, home: Path, *, cwd: str, resume: str | None, sandbox: str,
                    emit: Any) -> None:
        env = environment(prepared, home)
        config = home / "config.toml"
        client = self._client = AppServerClient([*agent_command(), codex, "app-server"], env=env, cwd=cwd,
                                                on_request=self._server_request)
        await client.start()
        self._check_stop()
        code, reason = codex_trust.hooks_refusal(
            await client.request("hooks/list", {"cwds": [cwd]}), config,
            hook_declarations(str(home / ENV_WRAPPER), guarded=True))
        if code:
            await self._refuse(emit, code, reason)
        approval = thread_approval(prepared)
        expected = codex_trust.launcher_servers(config)
        servers = set(expected)
        reason = codex_trust.layers_refusal(
            await client.request("config/read", {"cwd": cwd, "includeLayers": True}),
            mcp_servers=expected, approval=CONFIG_APPROVAL, sandbox=sandbox)
        if reason:
            await self._refuse(emit, "codex_repository_config_active", reason)
        self._check_stop()
        # Thread overrides rank above any repository layer that might still load.
        settings = {"cwd": cwd, "approvalPolicy": approval, "approvalsReviewer": "user", "sandbox": sandbox,
                    "config": {"shell_environment_policy": shell_environment(prepared),
                               **{f"mcp_servers.{name}.enabled": True for name in servers}}}
        if resume:
            reply = await client.request("thread/resume", {"threadId": resume, **settings})
        else:
            reply = await client.request("thread/start", settings)
        self._thread = str((reply.get("thread") or {}).get("id") or "")
        if (not self._thread or reply.get("approvalPolicy") != approval or reply.get("approvalsReviewer") != "user"
                or (reply.get("sandbox") or {}).get("type") != _SANDBOX_TYPES[sandbox]):
            await self._refuse(emit, "codex_thread_settings_mismatch", "thread_settings")
        roots = codex_trust.sandbox_roots(reply.get("sandbox") or {}, cwd)
        if sandbox == "workspace-write" and codex_trust.writable_in_sandbox(self._chain, roots):
            await self._refuse(emit, "codex_hook_chain_writable", "thread_sandbox_root")
        code, reason = codex_trust.hooks_refusal(
            await client.request("hooks/list", {"threadId": self._thread}), config,
            hook_declarations(str(home / ENV_WRAPPER), guarded=True))
        if code:
            await self._refuse(emit, code, reason)
        await self._admit_tools(client, servers, platform_origin(prepared), emit)

    async def _preflight(self, home: Path, *, cwd: str, sandbox: str, emit: Any) -> None:
        # Codex lets a call run when it cannot start the hook: the guard must run before the turn may start.
        if not await asyncio.to_thread(codex_trust.guard_runs, guard_command(str(home / ENV_WRAPPER))):
            await self._refuse(emit, "codex_hook_guard_unavailable", "guard_probe")
        if sandbox == "workspace-write" and codex_trust.writable_in_sandbox(self._chain,
                                                                         codex_trust.sandbox_roots({}, cwd)):
            await self._refuse(emit, "codex_hook_chain_writable", "sandbox_root")

    async def _refuse(self, emit: Any, code: str, reason: str) -> None:
        await emit({"kind": "error", "message": f"{code}: {reason}"})
        raise DriverStartError(code)

    async def _admit_tools(self, client: AppServerClient, servers: set[str], origin: str, emit: Any) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + MCP_READY_SECONDS
        reason = "not_listed"
        try:
            inventory = await client.request("mcpServerStatus/list",
                                             {"threadId": self._thread, "detail": "toolsAndAuthOnly"},
                                             timeout=max(deadline - loop.time(), 0.001))
            if (refused := codex_trust.unexpected_servers(inventory, servers)):
                await self._refuse(emit, "codex_repository_config_active", refused)
            while (left := deadline - loop.time()) > 0:
                self._check_stop()
                listed = await client.request(
                    "mcpServerStatus/list",
                    {"threadId": self._thread, "serverName": CODEX_MCP_SERVER, "detail": "toolsAndAuthOnly"},
                    timeout=left)
                server = next((row for row in listed.get("data") or [] if isinstance(row, dict)
                               and row.get("name") == CODEX_MCP_SERVER), {})
                status = server.get("runtimeStatus") if server.get("runtimeStatus") in _MCP_STATES else "unknown"
                if status == "connected" and server.get("tools"):
                    if canonical_origin(str(server.get("httpOrigin") or "")) != origin:
                        reason = "origin_changed"
                        break
                    return
                if server.get("toolsError") or status in ("failed", "authenticationRequired", "disabled", "cancelled"):
                    http = _HTTP_STATUS.search(str(server.get("toolsError") or ""))
                    reason = f"http_{http.group(1)}" if http else (status if status != "connected" else "tools_error")
                    break
                reason = "not_listed" if not server else status
                await asyncio.sleep(min(MCP_READY_POLL_SECONDS, max(deadline - loop.time(), 0)))
            else:
                reason = f"timeout_{reason}"
        except AppServerError as exc:
            reason = f"status_{exc.code}"
        await self._refuse(emit, "codex_platform_tools_unavailable", reason)

    async def _rounds(self, prepared: Any, *, cwd: str, prompt: str, emit: Any, result: dict[str, Any],
                      usage: dict[str, int]) -> bool:
        from . import plain_driver  # noqa: PLC0415

        for _round in range(MAX_STOP_CONTINUATIONS + 1):
            await asyncio.to_thread(plain_driver.discard_deferred_stop, prepared)
            if self._chain_hashes != await asyncio.to_thread(codex_trust.content_hashes, self._chain_files):
                result["error"] = "codex_hook_chain_changed"
                return False
            if not await self._turn_once(prompt, emit=emit, result=result, usage=usage):
                return False
            captured = await asyncio.to_thread(plain_driver.deferred_stop_input, prepared) or {}
            if not self._ours(captured):
                result["error"] = "codex_stop_unjudged"
                return False
            await asyncio.to_thread(plain_driver.discard_stop_verdict, prepared)
            answer, judged = await asyncio.to_thread(plain_driver.judged_stop, prepared, cwd, self._wrapper,
                                                     agent_command())
            verdict = await asyncio.to_thread(plain_driver.stop_verdict, prepared)
            self._check_stop()
            reason = str((answer or {}).get("reason") or "").strip()
            if not judged or not self._ours(verdict) or verdict.get("outcome") != "ok":
                result["error"] = "codex_stop_unjudged"
                return False
            if verdict.get("state") in _STOP_PASSED:
                notice = str((answer or {}).get("systemMessage") or "").strip()
                if notice:
                    await emit({"kind": "text", "text": _clip(notice, 2000)})
                return True
            if not verdict.get("blocked") or (answer or {}).get("decision") != "block" or not reason:
                capped = verdict.get("state") == "blocked" and not verdict.get("blocked")
                result["error"] = "codex_stop_unverified" if capped else "codex_stop_unjudged"
                return False
            await emit({"kind": "text", "text": _clip(f"Octryx: {reason}", 2000)})
            prompt = reason
        result["error"] = "codex_stop_continuations_exhausted"
        return False

    def _ours(self, record: dict[str, Any]) -> bool:
        return bool(self._thread) and record.get("session_id") == self._thread and record.get("turn_id") == self._turn

    async def _compact(self, *, emit: Any, result: dict[str, Any], usage: dict[str, int]) -> bool:
        client = self._client
        if client is None:
            raise CodexStoppedError
        await client.request("thread/compact/start", {"threadId": self._thread})
        while True:
            message = await asyncio.wait_for(client.next_notification(), TURN_TIMEOUT)
            method, params = message.get("method"), message.get("params") or {}
            if method == EXITED:
                result["error"] = "codex_app_server_exited"
                return False
            if params.get("threadId") not in (None, self._thread):
                continue
            if method == "thread/tokenUsage/updated":
                token_usage = params.get("tokenUsage") or {}
                for key, value in usage_of(token_usage.get("last")).items():
                    usage[key] = usage.get(key, 0) + value
                if (context := context_of(token_usage)) is not None:
                    await emit(context)
            elif method == "turn/completed":
                status = str((params.get("turn") or {}).get("status") or "")
                if status != "completed":
                    result["error"] = f"codex_compact_{status or 'failed'}"
                return status == "completed"

    async def _turn_once(self, prompt: str, *, emit: Any, result: dict[str, Any], usage: dict[str, int]) -> bool:
        client = self._client
        if client is None:
            raise CodexStoppedError
        self._check_stop()
        reply = await client.request("turn/start", {"threadId": self._thread,
                                                          "input": [{"type": "text", "text": prompt}]})
        self._turn = str((reply.get("turn") or {}).get("id") or "")
        if not self._turn:
            result["error"] = "codex_turn_unstarted"
            return False
        if self._stopped:
            await self.interrupt()
        answer = ""
        fatal = ""
        while True:
            message = await asyncio.wait_for(client.next_notification(), TURN_TIMEOUT)
            method, params = message.get("method"), message.get("params") or {}
            if method == EXITED:
                result["error"] = "codex_app_server_exited"
                return False
            if params.get("threadId") not in (None, self._thread) or params.get("turnId") not in (None, self._turn):
                continue
            if method in ("item/started", "item/completed") and isinstance(params.get("item"), dict):
                item = params["item"]
                ours = params.get("threadId") == self._thread and params.get("turnId") == self._turn
                for event in map_item(method, item):
                    if (event["kind"] == "text" and ours and item.get("phase") in _ANSWER_PHASES
                            and item["text"].strip()):
                        answer = event["text"]
                    await emit(event)
            elif method == "item/agentMessage/delta" and params.get("delta"):
                await emit({"kind": "text_delta", "text": str(params["delta"])})  # the chat streams the answer
            elif method == "hook/completed" and isinstance(params.get("run"), dict):
                for event in map_hook(params["run"]):
                    await emit(event)
            elif method == "thread/tokenUsage/updated":
                token_usage = params.get("tokenUsage") or {}
                for key, value in usage_of(token_usage.get("last")).items():
                    usage[key] = usage.get(key, 0) + value
                if (context := context_of(token_usage)) is not None:
                    await emit(context)  # the chat's context meter
            elif method == "error" and not params.get("willRetry"):
                fatal = limit_code(params.get("error")) or error_kind(params.get("error"))
                await emit({"kind": "error", "message": fatal})
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                if params.get("threadId") != self._thread or turn.get("id") != self._turn:
                    continue
                status = turn.get("status")
                status = status if status in _TURN_STATES else "unknown"
                if status == "completed" and answer and not fatal:
                    result["result_text"] = answer
                    return True
                result["error"] = (limit_code(turn.get("error")) or fatal
                                   or ("codex_turn_empty" if status == "completed" else f"codex_turn_{status}"))
                return False

    async def _server_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "item/commandExecution/requestApproval":
            verdict = await self._ask("Bash", {"command": str(params.get("command") or ""),
                                               "reason": params.get("reason")})
            return {"decision": "accept" if verdict else "decline"}
        if method == "item/fileChange/requestApproval":
            verdict = await self._ask("apply_patch", {"reason": params.get("reason"),
                                                      "grant_root": params.get("grantRoot")})
            return {"decision": "accept" if verdict else "decline"}
        if method == "item/permissions/requestApproval":
            requested = params.get("permissions") if isinstance(params.get("permissions"), dict) else {}
            verdict = await self._ask("RequestPermissions", {"permissions": requested,
                                                             "reason": params.get("reason")})
            return {"permissions": requested if verdict else {}, "scope": "turn"}
        if method == "mcpServer/elicitation/request":
            meta = params.get("_meta") or {}
            if meta.get("codex_approval_kind") != "mcp_tool_call":
                return {"action": "decline"}
            tool = f"mcp__{params.get('serverName', '')}__{meta.get('tool_name', '')}"
            verdict = await self._ask(tool, meta.get("tool_params") or {})
            return {"action": "accept", "content": {}} if verdict else {"action": "decline"}
        raise UnknownServerRequestError(method)

    async def _ask(self, tool: str, tool_input: dict[str, Any]) -> bool:
        if self._decide is None or self._stopped:
            return False
        try:
            verdict, _message = await self._decide(tool, tool_input)
        except Exception:  # noqa: BLE001 - an approval that could not be asked is a no
            return False
        return verdict in ("allow", "allow_job_edits") and not self._stopped

    @staticmethod
    async def _heartbeat(emit: Any, result: dict[str, Any]) -> None:
        # The platform ends a turn that is silent for 10 minutes; a long model call or command prints nothing.
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            thread = result.get("claude_session_id")
            await emit({"kind": "session", "claude_session_id": thread} if thread else {"kind": "heartbeat"})

    async def interrupt(self) -> None:
        self._stopped = True
        client = self._client
        if client is None or not client.running or not self._turn:
            return
        try:
            await client.request("turn/interrupt", {"threadId": self._thread, "turnId": self._turn},
                                       timeout=INTERRUPT_TIMEOUT)
        except AppServerError:
            await self.disconnect()

    async def disconnect(self) -> None:
        self._stopped = True
        client, self._client = self._client, None
        if client is not None:
            await client.close()


def hook_chain(home: Path, prepared: Any) -> list[Path]:
    from . import codex_hook_guard  # noqa: PLC0415

    package = Path(codex_trust.__file__).parent
    folders = [Path(folder) for folder in hook_path(prepared).split(os.pathsep) if folder]
    return [home, Path(sys.executable), package, Path(codex_hook_guard.__file__), Path("/bin/sh"), *folders]


def canonical_origin(url: str) -> str:
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return ""
    scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    if not scheme or not host:
        return ""
    host = f"[{host}]" if ":" in host else host
    default = {"http": 80, "https": 443}.get(scheme)
    return f"{scheme}://{host}" + (f":{port}" if port is not None and port != default else "")


def platform_origin(prepared: Any) -> str:
    return canonical_origin(str((prepared.extra.get("gateway") or {}).get("base_url") or ""))


def error_kind(error: Any) -> str:
    info = error.get("codexErrorInfo") if isinstance(error, dict) else None
    kind = info if isinstance(info, str) else next(iter(info), "") if isinstance(info, dict) else ""
    return f"codex_error_{kind if kind in _ERROR_KINDS else 'other'}"


def runs_codex(offer: dict[str, Any]) -> bool:
    return str(offer.get("engine") or "") == ENGINE


__all__ = [
    "CodexDriver",
    "CodexUnavailableError",
    "resolve_codex",
    "runs_codex",
]
