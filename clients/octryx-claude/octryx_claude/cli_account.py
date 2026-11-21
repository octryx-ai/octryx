"""The account subcommands: login, status, the token helpers Claude Code calls, the context-manager switch.

Messages carry fixed reason codes only; tokens, passwords and response bodies are never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import httpx

from . import (
    PRODUCT_VERSION,
    __version__,
    configure_cli,
    engine_choice,
    launch,
    profile_choice,
    seat_login,
    status_block,
    usage,
    workspaces,
)
from .cli_session import aliases, codes, fail
from .oauth import LoginError, headless_login, interactive_login
from .platform import SessionContext, call_control_plane, valid_header_value
from .state import LocalState
from .tokens import GATEWAY_AUDIENCE, MCP_AUDIENCE, TokenUnavailableError, get_access_token

POLICY_TIMEOUT = 15.0


def seat_login_command(state: LocalState) -> int:
    """``login --seat``: the subscription login of the seat profile only; the platform login is not needed."""
    try:
        claude = launch.resolve_claude()
    except launch.LaunchRefusedError as exc:
        return fail(f"needs_configuration: {exc.code}")
    return seat_login.run_seat_login(state, claude)

def login_command(args: argparse.Namespace, state: LocalState) -> int:
    if args.seat:
        if args.base_url or args.workspace or args.headless:
            return fail("login --seat takes no other option")
        return seat_login_command(state)
    config = state.config()
    base_url = configure_cli.normalized_base_url(args.base_url or str(config.get("base_url") or ""))
    if not base_url:
        return fail("needs_configuration: base_url_missing (pass --base-url https://...)")
    try:
        with httpx.Client(follow_redirects=False) as http:
            if args.headless:
                headless_login(state, base_url, http=http)
            else:
                interactive_login(state, base_url, http=http)
    except LoginError as exc:
        return fail(f"login failed: {exc.code}")
    config["base_url"] = base_url
    selected = None
    requested = args.workspace or configure_cli.pending_workspace(config)  # the installer's choice, see configure
    if requested:
        # A Workspace id or name: resolved with the new login, stored as the id.
        try:
            with httpx.Client() as http:
                selected = workspaces.resolve_workspace(
                    requested, workspaces.fetch_workspaces(state, http, base_url))
        except workspaces.WorkspaceError as exc:
            state.write_config(config)
            return fail(f"logged in, but the Workspace was not selected: {exc}")
        config["workspace_id"], config["workspace_name"] = selected.id, selected.name
        config.pop(configure_cli.REQUEST_KEY, None)
    state.write_config(config)
    print(f"Logged in to {base_url}." + (f" Workspace: {selected.label()}." if selected else ""))
    return 0

def status_command(state: LocalState) -> int:
    config = state.config()
    credentials = state.credentials()
    base_url = str(config.get("base_url") or "")
    logged_in = bool(credentials.get("refresh_token")) and credentials.get("base_url") == base_url
    tokens = credentials.get("tokens") if isinstance(credentials.get("tokens"), dict) else {}
    gateway = tokens.get(GATEWAY_AUDIENCE) if isinstance(tokens.get(GATEWAY_AUDIENCE), dict) else {}
    expires_at = float(gateway.get("expires_at") or 0)
    workspace_id = str(config.get("workspace_id") or "")
    workspace = "(not selected)"
    if not workspace_id and configure_cli.pending_workspace(config):
        workspace = f"{configure_cli.pending_workspace(config)} (selected at the next login)"
    if workspace_id:
        workspace = workspaces.label_for(config, workspace_id)
        if logged_in and valid_header_value(workspace_id):
            with httpx.Client() as http:
                workspace = workspaces.resolved_label(state, http, base_url, config, workspace_id)
    lines = [
        f"launcher:   octryx-claude {__version__} (launcher version; Octryx AI {PRODUCT_VERSION})",
        f"state dir:  {state.root}",
        f"base URL:   {base_url or '(not configured)'}",
        f"workspace:  {workspace}",
        f"work item:  {config.get('work_item') or '(none)'}",
        f"aliases:    {json.dumps(config.get('aliases') or launch.DEFAULT_ALIASES, sort_keys=True)}",
        f"login:      {'logged in' if logged_in else 'not logged in (run: octryx-claude login)'}",
    ]
    if logged_in and expires_at:
        valid_until = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at))
        lines.append(f"gateway access token valid until {valid_until} (refreshes automatically)")
    if logged_in and valid_header_value(workspace_id):
        context = SessionContext(base_url, str(uuid.uuid4()), workspace_id)
        with httpx.Client() as http:
            result = call_control_plane(state, context, "GET", "/client-policy", http=http, timeout=POLICY_TIMEOUT)
            usage_result = usage.fetch_usage(state, context, http=http) if status_block.policy_ok(result) else None
            engine = engine_choice.fetch(state, context, http=http)
        lines.append(f"engine:     {engine.line()}")
        lines += status_block.lines_for(state, result, codes(result), workspace=workspace,
                                        requested=profile_choice.PROFILE_AUTO, model=aliases(config)["main"],
                                        upcoming=True, usage_result=usage_result)
    print("\n".join(lines))
    return 0

def api_key_helper(state: LocalState) -> int:
    try:
        with httpx.Client() as http:
            token = get_access_token(state, GATEWAY_AUDIENCE, http=http)
    except TokenUnavailableError as exc:
        return fail(f"no gateway token ({exc.code}); run: octryx-claude login", 1)
    sys.stdout.write(token)
    return 0

def mcp_headers(state: LocalState) -> int:
    try:
        with httpx.Client() as http:
            token = get_access_token(state, MCP_AUDIENCE, http=http)
    except TokenUnavailableError as exc:
        return fail(f"no knowledge MCP token ({exc.code}); run: octryx-claude login", 1)
    headers = {"Authorization": f"Bearer {token}"}
    context = SessionContext.from_env()
    if context is not None:
        headers.update(context.headers())
    sys.stdout.write(json.dumps(headers))
    return 0

def context_manager_command(args: argparse.Namespace, state: LocalState) -> int:
    """The context manager is on by default and can be switched off here."""
    from . import (
        context_manager,  # noqa: PLC0415
        session_lessons,  # noqa: PLC0415
    )

    if args.context_action == "status":
        print("context manager: " + ("on" if context_manager.enabled(state) else "off")
              + " · lessons for the team: " + ("on" if session_lessons.enabled(state) else "off"))
        return 0
    if args.context_action == "lessons":
        if args.lessons_switch is None:
            print("lessons for the team: " + ("on" if session_lessons.enabled(state) else "off"))
            return 0
        config = state.config()
        config["session_lessons"] = args.lessons_switch == "on"
        state.ensure().write_config(config)
        print("Lessons on: after compactions and at the end this Mac sends the session's facts (paths, no file "
              "contents, secrets removed); the Workspace decides whether lessons are proposed."
              if args.lessons_switch == "on" else "Lessons off: this Mac sends no session facts.")
        return 0
    config = state.config()
    config["context_manager"] = args.context_action == "on"
    state.ensure().write_config(config)
    print("Context manager on: sessions keep goal, requests, changed files, tests and todos when they compact."
          if args.context_action == "on" else "Context manager off: Claude Code compacts on its own.")
    return 0


__all__ = ["api_key_helper", "context_manager_command", "login_command", "mcp_headers", "seat_login_command",
           "status_command"]
