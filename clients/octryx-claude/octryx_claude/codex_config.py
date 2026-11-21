"""Codex CLI's per-session home.

config.toml (the Octryx model provider, hooks, MCP servers), the env wrapper and the shared threads folder.
"""

from __future__ import annotations

import contextlib
import json
import shlex
from pathlib import Path
from typing import Any

from octryx_claude import launch_settings

from .codex_hook_input import CODEX_MCP_SERVER
from .device_sdk import DriverStartError

OPENAI_GATEWAY_PATH = "/api/v1/model-gateway/openai/v1"

PROVIDER_ID = "octryx"

HOME_DIR = "codex-home"

# Codex's thread files (``sessions/…/rollout-*.jsonl``) of every session on this device, in one folder: the epic's
# next story runs in a new launcher session (its own CODEX_HOME) and resumes the thread of the story before it.
THREADS_DIR = "codex-threads"

ENV_WRAPPER = "octryx-env.sh"

TOKEN_REFRESH_MS = 4 * 60 * 1000

NOTE = (
    "You build a story of an Octryx epic in this repository; the story is in the user's message. "
    "Never commit or push: the platform takes your changes as a patch. "
    "Before you end your turn, make sure your commands have finished. "
    "The platform then runs the declared tests and an independent review and sends anything red back to this session."
)

def _toml(value: Any) -> str:
    """A TOML value: JSON strings, numbers, booleans and arrays of them are valid TOML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml(item) for item in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)

def _inline(table: dict[str, str]) -> str:
    return "{ " + ", ".join(f"{json.dumps(key)} = {_toml(value)}" for key, value in table.items()) + " }"

def hook_env(prepared: Any) -> dict[str, str]:
    """What the hook entry needs to find its session: the launcher's own variables (no credentials)."""
    from .codex_hook_input import CODEX, ENGINE_ENV  # noqa: PLC0415
    from .hooks import DEFER_STOP_ENV  # noqa: PLC0415

    env = {key: value for key, value in prepared.env.items() if key.startswith("OCTRYX_")}
    env[DEFER_STOP_ENV] = "1"
    env[ENGINE_ENV] = CODEX  # the hooks know they answer Codex (no ``ask``)
    if prepared.env.get("PATH"):
        env["PATH"] = prepared.env["PATH"]
    return env

def write_env_wrapper(home: Path, prepared: Any, shim: str) -> Path:
    """Codex runs hooks with a login shell (whose profile may reset the environment) and the MCP headers helper
    with an empty environment (``python_not_found``, exit 2). Every launcher command Codex runs
    goes through this wrapper, which sets the launcher's variables again (no credentials among them)."""
    lines = ["#!/bin/sh"]
    lines += [f"export {key}={shlex.quote(value)}" for key, value in sorted(hook_env(prepared).items())]
    lines += [f'exec {shlex.quote(shim)} "$@"']
    path = home / ENV_WRAPPER
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o700)
    return path

def _hook_block(event: str, command: str, timeout: int, matcher: str = "") -> list[str]:
    lines = [f"[[hooks.{event}]]"]
    if matcher:
        lines.append(f"matcher = {_toml(matcher)}")
    lines += [f"[[hooks.{event}.hooks]]", 'type = "command"', f"command = {_toml(command)}", f"timeout = {timeout}", ""]
    return lines

def _provider(*, base_url: str, headers: dict[str, str], wrapper: str, seat: bool, seat_proxy: str = "",
              web: bool = False) -> list[str]:
    """The session's only provider: the platform's governed Responses gateway, or its seat route (the person's own
    ChatGPT login, ``codex_seat``; the seat credential comes from the process environment, never a file). With the
    platform's ``seat_traffic`` on ``device``, the seat's provider is the job's loopback seat proxy
    (``codex_seat_proxy``, ``seat_proxy`` = its URL), reached with the job's token from the process environment."""
    from .codex_seat import SEAT_CREDENTIAL_ENV, SEAT_CREDENTIAL_HEADER, SEAT_PROVIDER_ID, SEAT_ROUTE  # noqa: PLC0415
    from .codex_seat_proxy import PROXY_TOKEN_ENV
    from .seat_proxy_http import PROXY_TOKEN_HEADER  # noqa: PLC0415

    if seat:
        env_headers = {SEAT_CREDENTIAL_HEADER: SEAT_CREDENTIAL_ENV,
                       **({PROXY_TOKEN_HEADER: PROXY_TOKEN_ENV} if seat_proxy else {})}
        return [f"[model_providers.{SEAT_PROVIDER_ID}]", 'name = "Octryx seat (ChatGPT)"',
                f"base_url = {_toml(seat_proxy or base_url + SEAT_ROUTE)}", 'wire_api = "responses"',
                "requires_openai_auth = true", f"http_headers = {_inline(headers)}",
                f"env_http_headers = {_inline(env_headers)}",
                # A turn with the web searches with Codex's standalone ``web.run`` (the gpt-6 models are Responses Lite,
                # which never offers the hosted web_search): offered for a custom provider only with this
                # flag, and sent to ``<base_url>/alpha/search``, which only the device's seat proxy serves.
                *(["supports_standalone_web_search = true"] if web and seat_proxy else []), ""]
    return [f"[model_providers.{PROVIDER_ID}]", 'name = "Octryx"',
            f"base_url = {_toml(base_url + OPENAI_GATEWAY_PATH)}", 'wire_api = "responses"',
            f"http_headers = {_inline(headers)}", "",
            f"[model_providers.{PROVIDER_ID}.auth]", f"command = {_toml(wrapper)}", 'args = ["api-key-helper"]',
            f"refresh_interval_ms = {TOKEN_REFRESH_MS}", ""]

def _browser_server(spec: dict[str, Any] | None) -> list[str]:
    """The phase's own browser (``browser_mcp.server_spec``, only when the phase opted in): the same Playwright MCP
    server, arguments and restrictions as a Claude Code turn (own profile under the session folder, loopback origins,
    the platform's port blocked, downloads off). Its name has no ``-``, so Codex shows the tools as
    ``mcp__playwright__browser_*`` like Claude Code, and the hooks decide them alike (``run_shell.browser_rule``)."""
    from . import browser_mcp  # noqa: PLC0415

    if not isinstance(spec, dict) or not spec.get("command"):
        return []
    lines = [f"[mcp_servers.{browser_mcp.SERVER_NAME}]", f"command = {_toml(spec['command'])}",
             f"args = {_toml([str(arg) for arg in spec.get('args') or []])}"]
    env = spec.get("env") if isinstance(spec.get("env"), dict) else {}
    if env:
        lines.append(f"env = {_inline({str(key): str(value) for key, value in env.items()})}")
    # exec mode (approval ``never``) declines MCP tools without it; the PreToolUse hook decides every call.
    return [*lines, 'default_tools_approval_mode = "approve"', ""]

def config_toml(*, base_url: str, headers: dict[str, str], model: str, wrapper: str, sandboxed: bool,
                interactive: bool = False, story: bool = False, seat: bool = False,
                browser: dict[str, Any] | None = None, seat_proxy: str = "", web: bool = False) -> str:
    from .codex_seat import SEAT_PROVIDER_ID  # noqa: PLC0415

    hook = f"{shlex.quote(wrapper)} hook"
    pre_tool_use = (f"{hook} pre-tool-use || "
                    "{ echo 'Octryx hook failed; tool call denied (fail closed).' >&2; exit 2; }")
    lines = [
        "# Written by octryx for one session. Models only through the platform; no key on disk.",
        f"model_provider = {_toml(SEAT_PROVIDER_ID if seat else PROVIDER_ID)}",
        *([f"model = {_toml(model)}"] if model else []),
        # A seat session reads the person's own login through its auth.json link; any other stores nothing.
        f"cli_auth_credentials_store = {_toml('file' if seat else 'ephemeral')}",
        # A device turn cannot ask anyone; the terminal (``octryx codex``) asks the person before a command.
        f"approval_policy = {_toml('on-request' if interactive else 'never')}",
        f"sandbox_mode = {_toml('workspace-write' if sandboxed else 'danger-full-access')}",
        # Only an epic's story session (plain, decided on the device) gets the story note; any other phase follows
        # the platform's prompt and run contract, and the terminal session is the person's own.
        *([f"developer_instructions = {_toml(NOTE)}"] if story and not interactive else []),
        "check_for_update_on_startup = false",
        # No provider-hosted web search: it bypasses the platform's tools and egress, and company models refuse the
        # tool type ("Tool type 'web_search' is not supported").
        # Except a turn with the web (the offer's ``web``) on the person's seat (a server may not reach the web, so
        # research runs on the device): the search runs at the provider, the call leaves from this device and the
        # platform records each search from the answer.
        f"web_search = {_toml('live' if web and seat else 'disabled')}",
        "",
        "[analytics]",
        "enabled = false",
        "",
        "[features]",
        "hooks = true",
        # Codex's own sub-agents (collaboration.spawn_agent): allow by default, block as an admin option, so the
        # platform admits their calls and they are on.
        "multi_agent = true",
        "",
        *_provider(base_url=base_url, headers=headers, wrapper=wrapper, seat=seat, seat_proxy=seat_proxy,
                   web=web),
        f"[mcp_servers.{CODEX_MCP_SERVER}]",
        f"url = {_toml(base_url + launch_settings.KNOWLEDGE_MCP_PATH)}",
        f"http_headers_helper = {_toml(f'{shlex.quote(wrapper)} mcp-headers')}",
        # Without it Codex declines the platform's MCP tools in exec mode (approval ``never``): the chat eval of
        # Measured it. The platform decides those calls itself (PreToolUse hook).
        'default_tools_approval_mode = "approve"',
        "",
        *_browser_server(browser),
        *_hook_block("PreToolUse", pre_tool_use, launch_settings.PRE_TOOL_USE_HOOK_TIMEOUT),
        *_hook_block("PostToolUse", f"{hook} post-tool-use", launch_settings.POST_TOOL_USE_HOOK_TIMEOUT),
        *_hook_block("Stop", f"{hook} stop", launch_settings.STOP_HOOK_TIMEOUT),
    ]
    return "\n".join(lines) + "\n"

def session_headers(prepared: Any) -> dict[str, str]:
    from . import launch  # noqa: PLC0415

    gateway = prepared.extra.get("gateway") or {}
    raw = launch.custom_headers(str(gateway.get("session_key") or prepared.session_key),
                                str(gateway.get("workspace_id") or ""), "", "",
                                str(gateway.get("workflow_run") or ""))
    return dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)

def prepare_home(prepared: Any, *, sandboxed: bool, interactive: bool = False, seat_proxy: str = "") -> Path:
    """The session's ``CODEX_HOME`` next to its other state (``<state>/sessions/<key>/codex-home``); ``seat_proxy``:
    the URL of the job's loopback seat proxy when the seat's calls leave from this device."""
    gateway = prepared.extra.get("gateway") or {}
    shim = str(prepared.extra.get("hook_shim") or prepared.env.get("OCTRYX_TEST_RUN_SHIM") or "")
    if not shim or not gateway.get("base_url"):
        raise DriverStartError("codex_session_incomplete")
    home = Path(prepared.settings_path).parent / HOME_DIR
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    share_threads(home, prepared)
    seat = bool(prepared.extra.get("codex_seat"))
    if seat:
        from .codex_seat import link_login  # noqa: PLC0415

        link_login(home, prepared.extra.get("state_root") or Path(prepared.settings_path).parents[2])
    wrapper = write_env_wrapper(home, prepared, shim)
    (home / "config.toml").write_text(config_toml(
        base_url=str(gateway["base_url"]), headers=session_headers(prepared),
        # A seat session uses Codex's own default model unless one is named; a governed one the device's alias.
        model=prepared.model or ("" if seat else str(prepared.extra.get("default_model") or "")),
        wrapper=str(wrapper), sandboxed=sandboxed, interactive=interactive,
        story=bool(prepared.extra.get("plain")), seat=seat,
        # A run phase that opted in to a browser (``browser_mcp``); never the terminal session or a chat turn.
        browser=prepared.extra.get("browser_mcp") if not interactive else None, seat_proxy=seat_proxy,
        web=prepared.extra.get("web") is True and not interactive),
        encoding="utf-8")
    return home

def share_threads(home: Path, prepared: Any) -> None:
    """``<home>/sessions`` is the device's shared thread folder (story 2 of a Codex epic ran in a
    new CODEX_HOME, ``codex exec resume <thread>`` found nothing and exited 1). Codex looks a thread up in its own
    database first and then by file name, so the shared files are enough; configuration and hooks stay per session."""
    root = prepared.env.get("OCTRYX_CLAUDE_HOME") or ""
    if not root:
        return
    shared = Path(root) / THREADS_DIR
    shared.mkdir(parents=True, exist_ok=True, mode=0o700)
    link = home / "sessions"
    if link.is_symlink() or not link.exists():
        with contextlib.suppress(FileNotFoundError):
            link.unlink()
        link.symlink_to(shared, target_is_directory=True)


def environment(prepared: Any, home: Path, *, proxy_token: str = "") -> dict[str, str]:
    env = {key: value for key, value in prepared.env.items() if not key.startswith(("ANTHROPIC_", "CLAUDE_CODE_"))}
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL"):
        env.pop(name, None)  # the session's provider is the platform, never a key of the person's shell
    env["CODEX_HOME"] = str(home)
    from .codex_hook_input import CODEX, ENGINE_ENV  # noqa: PLC0415
    from .codex_seat import SEAT_CREDENTIAL_ENV  # noqa: PLC0415

    env[ENGINE_ENV] = CODEX
    credential = str(prepared.extra.get("seat_credential") or "")
    if prepared.extra.get("codex_seat") and credential:
        env[SEAT_CREDENTIAL_ENV] = credential  # the seat route's session credential, in the process env only
    if proxy_token:
        from .codex_seat_proxy import PROXY_TOKEN_ENV  # noqa: PLC0415

        env[PROXY_TOKEN_ENV] = proxy_token  # the job's seat proxy token, in the process env only
    return env
