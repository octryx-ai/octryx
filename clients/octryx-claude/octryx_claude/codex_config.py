"""Codex CLI's per-session home: config.toml, the env wrapper and the shared threads folder."""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from octryx_claude import launch_settings

from . import codex_hook_guard
from .codex_hook_input import CODEX_MCP_SERVER
from .codex_trust import HookDeclaration, pin_hooks
from .device_sdk import DriverStartError
from .launch_sandbox import TEST_RUN_SHIM_ENV

OPENAI_GATEWAY_PATH = "/api/v1/model-gateway/openai/v1"

PROVIDER_ID = "octryx"

HOME_DIR = "codex-home"

# Codex's thread files (``sessions/…/rollout-*.jsonl``) of every session on this device, in one folder: the epic's
# next story runs in a new launcher session (its own CODEX_HOME) and resumes the thread of the story before it.
THREADS_DIR = "codex-threads"
CODEX_HOMES_DIR = "codex-homes"

ENV_WRAPPER = "octryx-env.sh"

# Set by the server runner image: without user namespaces Codex's sandbox cannot start; the container is the boundary.
CONTAINER_BOUNDARY_ENV = "OCTRYX_CODEX_CONTAINER_BOUNDARY"
ASK_BEFORE_CHANGES = "default"  # the chat's permission mode that asks before a change
CONFIG_APPROVAL = "on-request"

TOKEN_REFRESH_MS = 4 * 60 * 1000

NOTE = (
    "You build a story of an Octryx epic in this repository; the story is in the user's message. "
    "Never commit or push: the platform takes your changes as a patch. "
    "Before you end your turn, make sure your commands have finished. "
    "The platform then runs the declared tests and an independent review and sends anything red back to this session."
)

def _toml(value: Any) -> str:
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
    from .codex_hook_input import CODEX, ENGINE_ENV  # noqa: PLC0415

    env = {key: value for key, value in prepared.env.items()
           if key in SESSION_METADATA or key.startswith("GIT_CONFIG_")}  # the job folder as safe git directory
    env[ENGINE_ENV] = CODEX  # the hooks know they answer Codex (no ``ask``)
    return {**env, **agent_env(prepared)}


def agent_env(prepared: Any) -> dict[str, str]:
    # Under an agent account: its own HOME and the launcher's token broker instead of the credential file.
    if not agent_mode():
        return {}
    from .runner import AGENT_HOME, broker_socket  # noqa: PLC0415
    from .state import LocalState  # noqa: PLC0415
    from .token_broker import SOCKET_ENV  # noqa: PLC0415

    root = prepared.env.get("OCTRYX_CLAUDE_HOME") or ""
    return {SOCKET_ENV: str(broker_socket(LocalState(Path(root) if root else None))), "HOME": AGENT_HOME}


# Started by the wrapper with ``python -I``: nothing from the session's PATH, PYTHONPATH or work folder is imported.
_BOOT = "import sys; sys.path.insert(0, sys.argv.pop(1)); from octryx_claude.entry import main; sys.exit(main())"


def launcher_command() -> list[str]:
    return [sys.executable, "-I", "-c", _BOOT, str(Path(__file__).resolve().parents[1])]


def hook_path(prepared: Any) -> str:
    from . import tools  # noqa: PLC0415

    root = prepared.env.get("OCTRYX_CLAUDE_HOME") or ""
    launcher = tools.bin_dirs(Path(root)) if root else [str(Path(sys.executable).parent)]
    return os.pathsep.join([*launcher, *SYSTEM_PATH])

def write_env_wrapper(home: Path, prepared: Any) -> Path:
    path = home / ENV_WRAPPER
    env = {**hook_env(prepared), TEST_RUN_SHIM_ENV: str(path)}
    from .hooks import DEFER_STOP_ENV  # noqa: PLC0415

    lines = ["#!/bin/sh"]
    lines += [f"export {key}={shlex.quote(value)}" for key, value in sorted(env.items())]
    lines += [# Codex's Stop is deferred; the launcher's own replay of it sets 0.
              f': "${{{DEFER_STOP_ENV}:=1}}"; export {DEFER_STOP_ENV}',
              # A wrapped test run is the agent's own command and keeps its shell's PATH and PYTHONPATH (an item
              # worktree's sources first); everything else the launcher decides is out of the work folder's reach.
              f'case "$1" in test-run) ;; *) unset {" ".join(STEERING_ENV)}; '
              f'PATH={shlex.quote(hook_path(prepared))}; export PATH ;; esac',
              f'exec {shlex.join(launcher_command())} "$@"']
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755 if agent_mode() else 0o700)
    return path

GUARD_MARGIN_SECONDS = 5


def guard_command(wrapper: str) -> list[str]:
    return [sys.executable, "-I", str(Path(codex_hook_guard.__file__).resolve()),
            str(launch_settings.PRE_TOOL_USE_HOOK_TIMEOUT - GUARD_MARGIN_SECONDS), wrapper, "hook", "pre-tool-use"]


def hook_declarations(wrapper: str, *, guarded: bool = False) -> list[HookDeclaration]:
    hook = f"{shlex.quote(wrapper)} hook"
    # A device turn's PreToolUse is the guard itself (exec, no shell around it): Codex lets a call run when the
    # hook's runner fails, so nothing but the guard may stand between them.
    pre_tool_use = (f"exec {shlex.join(guard_command(wrapper))}" if guarded else
                    f"{hook} pre-tool-use || "
                    "{ echo 'Octryx hook failed; tool call denied (fail closed).' >&2; exit 2; }")
    return [HookDeclaration("PreToolUse", pre_tool_use, launch_settings.PRE_TOOL_USE_HOOK_TIMEOUT),
            HookDeclaration("PostToolUse", f"{hook} post-tool-use", launch_settings.POST_TOOL_USE_HOOK_TIMEOUT),
            HookDeclaration("Stop", f"{hook} stop", launch_settings.STOP_HOOK_TIMEOUT)]

def _hook_block(hook: HookDeclaration) -> list[str]:
    return [f"[[hooks.{hook.event}]]", f"[[hooks.{hook.event}.hooks]]", 'type = "command"',
            f"command = {_toml(hook.command)}", f"timeout = {hook.timeout}", ""]

# Tool shells get none of the launcher's variables and no platform credential (Codex passes the whole environment
# on by default, *TOKEN* included); the few that tools read come back by value (:func:`shell_environment`).
SHELL_ENVIRONMENT = {"inherit": "all", "ignore_default_excludes": False,
                     "exclude": ["OCTRYX_*", "ANTHROPIC_*", "CLAUDE_CODE_*"]}
SHELL_PASSTHROUGH = ("OCTRYX_TURN_MARK", "OCTRYX_BROWSER_CHANNEL", "OCTRYX_BROWSER_MISSING", "OCTRYX_NO_BUILD_CACHE")
# What the hook wrapper may carry: the session's facts, never a credential (the wrapper is a file).
SESSION_METADATA = frozenset({
    "OCTRYX_BASE_URL", "OCTRYX_BROWSER_CHANNEL", "OCTRYX_BROWSER_EXTERNAL", "OCTRYX_BROWSER_MISSING",
    "OCTRYX_CLAUDE_EXECUTABLE", "OCTRYX_CLAUDE_HOME", "OCTRYX_CODEX_CONTAINER_BOUNDARY", "OCTRYX_CODEX_PATH",
    "OCTRYX_CONTEXT_MANAGER", "OCTRYX_CREDENTIAL_SET", "OCTRYX_DEFER_SESSION_END", "OCTRYX_NO_BUILD_CACHE",
    "OCTRYX_PROFILE", "OCTRYX_SANDBOX_BRANCH", "OCTRYX_SANDBOX_RUN_ID", "OCTRYX_SESSION_KEY",
    "OCTRYX_SESSION_LESSONS", "OCTRYX_SESSION_MODE", "OCTRYX_TEST_RUN_SHIM", "OCTRYX_TURN_MARK",
    "OCTRYX_WORKFLOW_RUN", "OCTRYX_WORKSPACE", "OCTRYX_WORKSPACE_ID", "OCTRYX_WORK_ITEM", "OCTRYX_TOKEN_SOCKET",
    "OCTRYX_SHARED_STATE"})
LOGIN_CREDENTIALS = ("OCTRYX_USERNAME", "OCTRYX_PASSWORD")
SYSTEM_PATH = ("/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
# Variables that steer an interpreter or a shell started below the wrapper.
STEERING_ENV = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONINSPECT", "PYTHONEXECUTABLE",
                "PYTHONSAFEPATH", "PYTHONPLATLIBDIR", "PYTHONBREAKPOINT", "BASH_ENV", "ENV", "CDPATH", "IFS",
                "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH")


def shell_environment(prepared: Any) -> dict[str, Any]:
    kept = {name: prepared.env[name] for name in SHELL_PASSTHROUGH if prepared.env.get(name)}
    return {**SHELL_ENVIRONMENT, **({"set": kept} if kept else {})}

def _shell_environment() -> list[str]:
    return ["[shell_environment_policy]", *(f"{key} = {_toml(value)}" for key, value in SHELL_ENVIRONMENT.items()), ""]

def _provider(*, base_url: str, headers: dict[str, str], wrapper: str, seat: bool) -> list[str]:
    from .codex_seat import SEAT_CREDENTIAL_ENV, SEAT_CREDENTIAL_HEADER, SEAT_PROVIDER_ID, SEAT_ROUTE  # noqa: PLC0415

    if seat:
        return [f"[model_providers.{SEAT_PROVIDER_ID}]", 'name = "Octryx seat (ChatGPT)"',
                f"base_url = {_toml(base_url + SEAT_ROUTE)}", 'wire_api = "responses"',
                "requires_openai_auth = true", f"http_headers = {_inline(headers)}",
                f"env_http_headers = {_inline({SEAT_CREDENTIAL_HEADER: SEAT_CREDENTIAL_ENV})}", ""]
    return [f"[model_providers.{PROVIDER_ID}]", 'name = "Octryx"',
            f"base_url = {_toml(base_url + OPENAI_GATEWAY_PATH)}", 'wire_api = "responses"',
            f"http_headers = {_inline(headers)}", "",
            f"[model_providers.{PROVIDER_ID}.auth]", f"command = {_toml(wrapper)}", 'args = ["api-key-helper"]',
            f"refresh_interval_ms = {TOKEN_REFRESH_MS}", ""]

# No ``-`` in the server name, so Codex names the tools ``mcp__playwright__browser_*`` like Claude Code.
def _browser_server(spec: dict[str, Any] | None) -> list[str]:
    from . import browser_mcp  # noqa: PLC0415

    if not isinstance(spec, dict) or not spec.get("command"):
        return []
    lines = [f"[mcp_servers.{browser_mcp.SERVER_NAME}]", f"command = {_toml(spec['command'])}",
             f"args = {_toml([str(arg) for arg in spec.get('args') or []])}"]
    env = spec.get("env") if isinstance(spec.get("env"), dict) else {}
    if env:
        lines.append(f"env = {_inline({str(key): str(value) for key, value in env.items()})}")
    # The PreToolUse hook decides every call; Codex must not ask a second time.
    return [*lines, 'default_tools_approval_mode = "approve"', ""]

def config_toml(*, base_url: str, headers: dict[str, str], model: str, wrapper: str, sandboxed: bool,
                interactive: bool = False, story: bool = False, seat: bool = False,
                browser: dict[str, Any] | None = None, container_boundary: bool = False, device_turn: bool = False,
                context_window: int = 0) -> str:
    from .codex_seat import SEAT_PROVIDER_ID  # noqa: PLC0415

    lines = [
        "# Written by octryx for one session. Models only through the platform; no key on disk.",
        f"model_provider = {_toml(SEAT_PROVIDER_ID if seat else PROVIDER_ID)}",
        *([f"model = {_toml(model)}"] if model else []),
        # A gateway alias Codex does not know: its window from the platform, for the context it reports.
        *([f"model_context_window = {int(context_window)}"] if context_window > 0 else []),
        # A seat session reads the person's own login through its auth.json link; any other stores nothing.
        f"cli_auth_credentials_store = {_toml('file' if seat else 'ephemeral')}",
        # A one-shot ``codex exec`` cannot ask anyone; the terminal and a device turn ask through their client.
        f"approval_policy = {_toml('on-request' if interactive or device_turn else 'never')}",
        f"sandbox_mode = {_toml('workspace-write' if sandboxed and not container_boundary else 'danger-full-access')}",
        # Only an epic's story session (plain, decided on the device) gets the story note; any other phase follows
        # the platform's prompt and run contract, and the terminal session is the person's own.
        *([f"developer_instructions = {_toml(NOTE)}"] if story and not interactive else []),
        "check_for_update_on_startup = false",
        # No provider-hosted web search, on the seat too: it bypasses the platform's web tools and egress, and company
        # models refuse the tool type ("Tool type 'web_search' is not supported").
        'web_search = "disabled"',
        "",
        "[analytics]",
        "enabled = false",
        "",
        "[features]",
        "hooks = true",
        "multi_agent = true",
        "",
        *_provider(base_url=base_url, headers=headers, wrapper=wrapper, seat=seat),
        f"[mcp_servers.{CODEX_MCP_SERVER}]",
        f"url = {_toml(base_url + launch_settings.KNOWLEDGE_MCP_PATH)}",
        f"http_headers_helper = {_toml(f'{shlex.quote(wrapper)} mcp-headers')}",
        # The PreToolUse hook decides every platform tool call; Codex must not ask a second time.
        'default_tools_approval_mode = "approve"',
        "",
        *_browser_server(browser),
        *(_shell_environment() if device_turn else []),
        *(line for hook in hook_declarations(wrapper, guarded=device_turn) for line in _hook_block(hook)),
    ]
    return "\n".join(lines) + "\n"

def session_headers(prepared: Any) -> dict[str, str]:
    from . import launch  # noqa: PLC0415

    gateway = prepared.extra.get("gateway") or {}
    raw = launch.custom_headers(str(gateway.get("session_key") or prepared.session_key),
                                str(gateway.get("workspace_id") or ""), "", "",
                                str(gateway.get("workflow_run") or ""))
    return dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)

def prepare_home(prepared: Any, *, sandboxed: bool, interactive: bool = False, device_turn: bool = False) -> Path:
    gateway = prepared.extra.get("gateway") or {}
    shim = str(prepared.extra.get("hook_shim") or prepared.env.get("OCTRYX_TEST_RUN_SHIM") or "")
    if not shim or not gateway.get("base_url"):
        raise DriverStartError("codex_session_incomplete")
    home = codex_home(prepared)
    share_threads(home, prepared)
    seat = bool(prepared.extra.get("codex_seat"))
    if seat:
        from .codex_seat import link_login  # noqa: PLC0415

        link_login(home, prepared.extra.get("state_root") or Path(prepared.settings_path).parents[2])
    wrapper = write_env_wrapper(home, prepared)
    (home / "config.toml").write_text(config_toml(
        base_url=str(gateway["base_url"]), headers=session_headers(prepared),
        # A seat session uses Codex's own default model unless one is named; a governed one the device's alias.
        model=prepared.model or ("" if seat else str(prepared.extra.get("default_model") or "")),
        wrapper=str(wrapper), sandboxed=sandboxed, interactive=interactive,
        story=bool(prepared.extra.get("plain")), seat=seat,
        # A run phase that opted in to a browser (``browser_mcp``); never the terminal session or a chat turn.
        browser=prepared.extra.get("browser_mcp") if not interactive else None,
        container_boundary=container_boundary(prepared), device_turn=device_turn,
        context_window=int(prepared.extra.get("model_context_window") or 0)),
        encoding="utf-8")
    pin_hooks(home / "config.toml", hook_declarations(str(wrapper), guarded=device_turn))
    (home / "config.toml").chmod(0o644 if agent_mode() else 0o600)
    return home


def agent_mode() -> bool:
    from .runner import agent_uid  # noqa: PLC0415

    return agent_uid() is not None


def codex_home(prepared: Any) -> Path:
    # Under an agent account the home lies outside the session folder, in a folder only the launcher writes: Codex
    # may add its own files there (sticky), never replace the launcher's.
    if not agent_mode():
        home = Path(prepared.settings_path).parent / HOME_DIR
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        return home
    homes = Path(prepared.env.get("OCTRYX_CLAUDE_HOME") or "") / CODEX_HOMES_DIR
    homes.mkdir(parents=True, exist_ok=True)
    homes.chmod(0o2750)
    home = homes / Path(prepared.settings_path).parent.name
    home.mkdir(exist_ok=True)
    home.chmod(0o3770)
    return home

def container_boundary(prepared: Any) -> bool:
    return (prepared.env.get(CONTAINER_BOUNDARY_ENV) or os.environ.get(CONTAINER_BOUNDARY_ENV)) == "1"


def thread_approval(prepared: Any) -> str:
    # Behind a container boundary Codex has no sandbox whose refusal would make it ask, so "ask before changes" is
    # Codex's policy of asking before every command not known to be read-only. Per thread only: Codex 0.169 refuses
    # ``untrusted`` in config.toml.
    if container_boundary(prepared) and prepared.extra.get("permission_mode") == ASK_BEFORE_CHANGES:
        return "untrusted"
    return CONFIG_APPROVAL


def share_threads(home: Path, prepared: Any) -> None:
    # One thread folder per device: an epic's next story runs in a new CODEX_HOME and resumes the thread by id.
    root = prepared.env.get("OCTRYX_CLAUDE_HOME") or ""
    if not root:
        return
    shared = Path(root) / THREADS_DIR
    shared.mkdir(parents=True, exist_ok=True, mode=0o700)
    if agent_mode() and shared.stat().st_uid == os.getuid():
        shared.chmod(0o2770)  # Codex writes its threads under the agent's account
    link = home / "sessions"
    if link.is_symlink() or not link.exists():
        with contextlib.suppress(FileNotFoundError):
            link.unlink()
        link.symlink_to(shared, target_is_directory=True)


def environment(prepared: Any, home: Path) -> dict[str, str]:
    env = {key: value for key, value in prepared.env.items() if not key.startswith(("ANTHROPIC_", "CLAUDE_CODE_"))}
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL", *LOGIN_CREDENTIALS):
        env.pop(name, None)  # the session's provider is the platform, never a key of the person's shell
    env["CODEX_HOME"] = str(home)
    env.update(agent_env(prepared))
    from .codex_hook_input import CODEX, ENGINE_ENV  # noqa: PLC0415
    from .codex_seat import SEAT_CREDENTIAL_ENV  # noqa: PLC0415

    env[ENGINE_ENV] = CODEX
    credential = str(prepared.extra.get("seat_credential") or "")
    if prepared.extra.get("codex_seat") and credential:
        env[SEAT_CREDENTIAL_ENV] = credential  # the seat route's session credential, in the process env only
    return env
