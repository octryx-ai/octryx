"""Starting a terminal session for the Claude Code and Codex launches: target, engine check, registration, banner.
Messages carry fixed reason codes only; tokens and response bodies are never printed."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import uuid

import httpx

from octryx_claude import contract_notices, launch_process, launch_settings

from . import (
    __version__,
    configure_cli,
    engine_choice,
    install_layout,
    launch,
    mcp_auth_cache,
    run_contract,
    workspaces,
)
from .platform import PlatformResult, SessionContext, call_control_plane, safe_code, valid_header_value
from .snapshot import PREFIX as CODE_INTELLIGENCE_PREFIX
from .snapshot import run_code_intelligence
from .state import LocalState

SHIM = install_layout.launcher_shim()
REGISTER_TIMEOUT = 15.0
GIT_BRANCH_TIMEOUT = 2.0
CLIENT_NAME = "octryx-claude"
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]{0,199}$")


def fail(message: str, code: int = 2) -> int:
    sys.stderr.write(f"octryx-claude: {message}\n")
    return code

def codes(result: PlatformResult) -> str:
    return "/".join(part for part in (result.state, result.reason) if part) or result.outcome

def aliases(config: dict) -> dict[str, str]:
    raw = config.get("aliases") if isinstance(config.get("aliases"), dict) else {}
    aliases = dict(launch.DEFAULT_ALIASES)
    for key in aliases:
        value = str(raw.get(key) or "")
        if value and valid_header_value(value):
            aliases[key] = value
    return aliases

def code_intelligence(args: argparse.Namespace, state: LocalState, context: SessionContext) -> None:
    if args.no_code_intelligence:
        sys.stderr.write(f"{CODE_INTELLIGENCE_PREFIX}off (skipped_by_flag)\n")
        sys.stderr.flush()
        return
    try:
        with httpx.Client() as http:
            run_code_intelligence(state, context, os.getcwd(), http=http, out=sys.stderr)
    except Exception:  # noqa: BLE001 - the session starts anyway with code intelligence off
        sys.stderr.write(f"{CODE_INTELLIGENCE_PREFIX}off (internal_error)\n")
        sys.stderr.flush()

def git_branch() -> str | None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True,
            timeout=GIT_BRANCH_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    branch = done.stdout.strip() if done.returncode == 0 else ""
    return branch if _BRANCH.match(branch) else None

def register(state: LocalState, context: SessionContext, profile: str, purpose: str = "",
              engine: str = "") -> tuple[str, str]:
    body = {"profile": profile, "client": CLIENT_NAME, "client_version": __version__, "branch": git_branch()}
    if purpose:
        body["purpose"] = purpose
    if engine:
        body["engine"] = engine
    # The platform server's "needs authentication" mark from an earlier session would hide its tools for ~15 minutes;
    # the launcher authenticates that server itself (``mcp_auth_cache``), like a device turn. Claude Code only:
    # Codex keeps no such mark in this folder.
    if engine != engine_choice.CODEX and mcp_auth_cache.clear(state.claude_config_dir_for(profile),
                                                               launch_settings.MCP_SERVER_NAME):
        body["mcp_auth_cache_cleared"] = True
    with httpx.Client() as http:
        result = call_control_plane(
            state, context, "POST", "/sessions/register", http=http, timeout=REGISTER_TIMEOUT, body=body
        )
    if result.outcome != "ok" or result.state != "registered":
        return "", f"registration {codes(result)}"
    show_run(state, context, result.body)
    if profile != launch_process.PROFILE_SEAT:
        return "", ""
    credential = result.body.get("seat_credential")
    header = str(result.body.get("credential_header") or "")
    if header.lower() != launch.HEADER_SEAT_CREDENTIAL.lower() or not launch.valid_seat_credential(credential):
        return "", "registration invalid_response"
    return credential, ""

def show_run(state: LocalState, context: SessionContext, body: dict) -> None:
    contract = run_contract.remember(state, context.session_key, body)
    contract_notices.remember_platform_agent(state, context.session_key, body)  # also outside a run
    if contract:
        for line in contract_notices.banner(contract):
            sys.stderr.write(f"octryx-claude: {line}\n")
        contract_notices.changed_notice(state, context.session_key, contract)  # shown here, not again at the first hook
    elif isinstance(body.get("workflow_run_attach"), dict):
        attach = body["workflow_run_attach"]
        if safe_code(attach.get("state")) == "denied":
            sys.stderr.write(f"octryx-claude: work item run not attached ({safe_code(attach.get('reason'))})\n")

def session_target(args: argparse.Namespace, state: LocalState) -> tuple[str, str, str] | int:
    config = state.config()
    base_url = configure_cli.normalized_base_url(str(config.get("base_url") or ""))
    if not base_url or state.credentials().get("base_url") != base_url:
        return fail("needs_configuration: not_logged_in (run: octryx-claude login --base-url URL)")
    workspace_label = ""
    if args.workspace:
        # ``--workspace`` takes an id or a name; the name is resolved with this login.
        try:
            with httpx.Client() as http:
                chosen = workspaces.resolve_workspace(
                    args.workspace, workspaces.fetch_workspaces(state, http, base_url))
        except workspaces.WorkspaceError as exc:
            return fail(f"needs_configuration: {exc}")
        workspace_id, workspace_label = chosen.id, chosen.label()
    else:
        workspace_id = str(config.get("workspace_id") or "")
        workspace_label = workspaces.label_for(config, workspace_id)
        if valid_header_value(workspace_id):
            with httpx.Client() as http:
                workspace_label = workspaces.resolved_label(state, http, base_url, config, workspace_id)
    if not workspace_id:
        return fail("needs_configuration: workspace_not_selected (pass --workspace ID or NAME)")
    if not valid_header_value(workspace_id):
        return fail("denied: workspace_id_invalid")
    return base_url, workspace_id, workspace_label

def engine_refusal(state: LocalState, base_url: str, workspace_id: str, engine: str) -> str:
    with httpx.Client() as http:
        setting = engine_choice.fetch(state, SessionContext(base_url, str(uuid.uuid4()), workspace_id), http=http)
    return engine_choice.refusal(setting, engine)


__all__ = ["CLIENT_NAME", "SHIM", "aliases", "code_intelligence", "codes", "engine_refusal", "fail", "git_branch",
           "register", "session_target", "show_run"]
