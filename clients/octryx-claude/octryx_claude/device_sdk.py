"""Claude Code through the Claude Agent SDK for one device job turn."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from .device_sdk_events import (
    context_tokens,
    context_window,
    map_message,
)
from .device_session import PreparedSession
from .device_turn_kind import (
    DISABLE_BACKGROUND_ENV,
    INTERACTIVE_TOOLS,
    LOCAL_READ_TOOLS,
    PLAIN_THINKING,
    SETTING_SOURCES,
    WEB_ALLOWED,
    _lean_prompt,
    _lean_sources,
    _lean_tools,
    _run_turn,
    open_network_host,
    plain_session,
    run_compact_window,
    story_session,
    web_turn,
)
from .seat_status import turn_limit_code

Emit = Callable[[dict[str, Any]], Awaitable[None]]
# (tool, input) → ("allow" | "allow_job_edits" | "deny", message)
Decide = Callable[[str, dict[str, Any]], Awaitable[tuple[str, str]]]


class DriverUnavailableError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DriverStartError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


START_TIMEOUT_CODE = "claude_initialize_timeout"
START_FAILED_CODE = "claude_start_failed"


def start_error_code(exc: BaseException) -> str:
    # The SDK raises a plain Exception("Control request timeout: initialize"); it has no typed error for it.
    text = str(exc).lower()
    return START_TIMEOUT_CODE if "timeout" in text and "initialize" in text else START_FAILED_CODE


def load_sdk() -> Any:
    try:
        import claude_agent_sdk
    except ImportError as exc:
        raise DriverUnavailableError("claude_agent_sdk_missing") from exc
    return claude_agent_sdk


CONTEXT_STEP_TOKENS = 2000


def _can_use_tool(sdk: Any, prepared: PreparedSession, decide: Decide) -> Callable[..., Awaitable[Any]]:
    async def can_use_tool(tool_name: str, tool_input: dict[str, Any], context: Any) -> Any:
        if open_network_host(prepared, tool_name, tool_input):
            return sdk.PermissionResultAllow(updated_input=tool_input)
        verdict, message = await decide(tool_name, tool_input)
        if verdict == "allow":
            return sdk.PermissionResultAllow(updated_input=tool_input)
        if verdict == "allow_job_edits":
            return sdk.PermissionResultAllow(
                updated_input=tool_input,
                updated_permissions=[sdk.PermissionUpdate(type="setMode", mode="acceptEdits",
                                                          destination="session")])
        return sdk.PermissionResultDeny(message=message, interrupt=False)

    return can_use_tool


async def _keep_stream_open(hook_input: Any, tool_use_id: Any, context: Any) -> dict[str, Any]:
    # The Python SDK needs a PreToolUse hook registered for can_use_tool; this one decides nothing
    # (the platform's own PreToolUse hook in the settings still runs and can deny).
    return {"continue_": True}


async def _ask_the_phone(hook_input: Any, tool_use_id: Any, context: Any) -> dict[str, Any]:
    tool = str((hook_input or {}).get("tool_name") or "") if isinstance(hook_input, dict) else ""
    if tool in LOCAL_READ_TOOLS:
        return {"continue_": True}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": "Approve on your phone"}}


def _local_options(sdk: Any, prepared: PreparedSession, *, cwd: str, env: dict[str, str], resume: str | None,
                   fork: bool, can_use_tool: Any) -> Any:
    # Every non-read tool asks the phone, whatever the profile's allow rules: a phone-started action is explicit.
    state = str(prepared.extra.get("state_root") or "").lstrip("/")
    protected = {"permissions": {"deny": [f"Read(//{state}/**)", f"Edit(//{state}/**)"]}} if state else {}
    return sdk.ClaudeAgentOptions(
        cli_path=prepared.cli_path, cwd=cwd, env=env, setting_sources=list(SETTING_SOURCES),
        settings=json.dumps(protected) if protected else None,
        permission_mode="default", include_partial_messages=True, resume=resume or None,
        fork_session=bool(fork and resume),  # a copy of the session: the original's transcript stays its own
        model=prepared.model or None, can_use_tool=can_use_tool,
        hooks={"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[_ask_the_phone])]},
    )


def _lean_args(prepared: PreparedSession, env: dict[str, str], resume: str | None) -> tuple[dict[str, str | None], str]:
    extra_args: dict[str, str | None] = {"strict-mcp-config": None}
    lean = bool(prepared.extra.get("lean"))
    story = lean and story_session(prepared)
    if lean:
        extra_args.update({"disable-slash-commands": None, **({} if story else {"tools": _lean_tools(prepared)})})
    if story:
        # No background subagents: a headless turn that ends "waiting for their notifications" loses their work
        # and the pipeline runs on an empty change. Foreground subagents started in one message still run in
        # parallel.
        env[DISABLE_BACKGROUND_ENV] = "1"
    if lean and _run_turn(prepared):
        # A run turn never drives the person's Chrome (Claude in Chrome), whatever their own Claude Code says.
        extra_args["no-chrome"] = None
    mcp_servers = str(prepared.mcp_path)
    browser_spec = prepared.extra.get("browser_mcp")
    if lean and _run_turn(prepared) and isinstance(browser_spec, dict):
        # A browser of its own for this turn only (Playwright MCP, an isolated headless browser
        # per session, no extension): the job manager installed and described it (``browser_mcp.server_spec``)
        # for a run turn whose phase opted in (``browser``), a story session or a phase turn alike.
        from . import browser_mcp  # noqa: PLC0415

        mcp_servers = str(browser_mcp.browser_config(prepared.mcp_path, browser_spec))
    if not resume:
        extra_args["session-id"] = prepared.session_key
    return extra_args, mcp_servers


class SdkDriver:
    def __init__(self, sdk: Any = None) -> None:
        self._sdk = sdk
        self._client: Any = None

    @property
    def sdk(self) -> Any:
        if self._sdk is None:
            self._sdk = load_sdk()
        return self._sdk

    def _options(self, prepared: PreparedSession, *, cwd: str, resume: str | None, decide: Decide,
                 fork: bool = False) -> Any:
        sdk = self.sdk
        can_use_tool = _can_use_tool(sdk, prepared, decide)
        env = dict(prepared.env)
        window = run_compact_window(prepared)
        if window:  # 200k per session by default, at most 300k
            env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(window)
        if prepared.extra.get("local"):
            return _local_options(sdk, prepared, cwd=cwd, env=env, resume=resume, fork=fork,
                                  can_use_tool=can_use_tool)
        lean = bool(prepared.extra.get("lean"))
        story = lean and story_session(prepared)
        extra_args, mcp_servers = _lean_args(prepared, env, resume)
        # The chat's permission mode (bypass included) and effort. The platform's PreToolUse hook in
        # the settings runs in every mode; ``can_use_tool`` still asks the phone where Claude Code would ask.
        mode = str(prepared.extra.get("permission_mode") or "default")
        effort = str(prepared.extra.get("effort") or "") or None
        return sdk.ClaudeAgentOptions(
            cli_path=prepared.cli_path, settings=str(prepared.settings_path), mcp_servers=mcp_servers,
            cwd=cwd, env=env,
            setting_sources=_lean_sources(prepared) if lean and not plain_session(prepared) else list(SETTING_SOURCES),
            permission_mode=mode, effort=effort,
            **({"system_prompt": _lean_prompt(prepared)} if lean else {}),
            **({"disallowed_tools": list(INTERACTIVE_TOOLS)} if story else {}),
            **({"allowed_tools": list(WEB_ALLOWED)} if web_turn(prepared) else {}),
            **({"thinking": dict(PLAIN_THINKING)} if story and plain_session(prepared) else {}),
            include_partial_messages=True, resume=resume or None, model=prepared.model or None,
            can_use_tool=can_use_tool,
            hooks={"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[_keep_stream_open])]},
            extra_args=extra_args,
        )

    async def run_turn(self, prepared: PreparedSession, *, cwd: str, prompt: str, resume: str | None,
                       fork: bool = False,
                       decide: Decide, emit: Emit) -> dict[str, Any]:
        options = self._options(prepared, cwd=cwd, resume=resume, decide=decide, fork=fork)
        result: dict[str, Any] = {"status": "error", "result_text": "", "claude_session_id": resume}
        context = {"tokens": 0, "sent": 0}  # the app shows how full the context is
        async with contextlib.AsyncExitStack() as stack:
            try:
                client = await stack.enter_async_context(self.sdk.ClaudeSDKClient(options=options))
            except Exception as exc:  # noqa: BLE001 - every start failure becomes a fixed code
                raise DriverStartError(start_error_code(exc)) from exc
            self._client = client
            try:
                await client.query(prompt)
                async for message in client.receive_response():
                    for event in map_message(message):
                        if event["kind"] == "session":
                            result["claude_session_id"] = event["claude_session_id"]
                        await emit(event)
                    tokens = context_tokens(message)
                    if tokens is not None:
                        context["tokens"] = tokens
                        if abs(tokens - context["sent"]) >= CONTEXT_STEP_TOKENS:
                            context["sent"] = tokens
                            await emit({"kind": "context", "tokens": tokens})
                    limit = turn_limit_code(getattr(message, "error", None))
                    if limit and type(message).__name__ == "AssistantMessage":
                        # Claude Code's own error kind of the turn (``rate_limit``, ``billing_error``): the platform
                        # reads the seat's limit from this code, never from the text.
                        result["error"] = limit
                    if type(message).__name__ == "ResultMessage":
                        if context["tokens"]:
                            await emit({"kind": "context", "tokens": context["tokens"],
                                        "window": context_window(getattr(message, "model_usage", None))})
                        result.update({
                            "status": "error" if getattr(message, "is_error", False) else "success",
                            "result_text": str(getattr(message, "result", "") or ""),
                            # The session's running total (restored on resume), information only: the platform
                            # prices the turn's transcript usage (``transcript_usage``).
                            "cost_usd": getattr(message, "total_cost_usd", None),
                            "usage": getattr(message, "usage", None),
                            "claude_session_id": getattr(message, "session_id", None) or result["claude_session_id"],
                        })
            finally:
                self._client = None
        return result

    async def interrupt(self) -> None:
        if self._client is not None:
            await self._client.interrupt()

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()


__all__ = [
    "DriverStartError",
    "DriverUnavailableError",
    "SdkDriver",
    "load_sdk",
]
