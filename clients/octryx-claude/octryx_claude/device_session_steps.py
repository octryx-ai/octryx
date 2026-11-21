"""The parts of a device turn's session (``device_session.prepare_session``) that decide nothing on their own: the
policy check's verdict, the registration call, the settings, the child env and the session's extras for the drivers.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from octryx_claude import launch_process, launch_sandbox, launch_settings

from . import (
    __version__,
    browser_mcp,
    launch,
    mcp_auth_cache,
    model_picker,
    session_rules,
    status_block,
    workspace_prep,
)
from .platform import PlatformResult, SessionContext, call_control_plane, valid_header_value
from .seat_status import seat_refusal
from .state import CREDENTIAL_SET_DEVICE, CREDENTIAL_SET_ENV, LocalState

CLIENT_NAME = "octryx-claude-device"
TIMEOUT = 15.0


def _codes(result: PlatformResult) -> str:
    return "_".join(part for part in (result.state, result.reason) if part) or result.outcome


def _aliases(state: LocalState) -> dict[str, str]:
    raw = state.config().get("aliases")
    aliases = dict(launch.DEFAULT_ALIASES)
    if isinstance(raw, dict):
        for key in aliases:
            value = str(raw.get(key) or "")
            if value and valid_header_value(value):
                aliases[key] = value
    return aliases


def policy_refusal(policy: PlatformResult, *, profile: str, model: str, engine: str) -> str:
    """The client policy's refusal of this turn, else ``""``."""
    if not status_block.policy_ok(policy):
        return f"client_policy_{_codes(policy)}"[:80]
    # The Claude seat's policy and model picker; a Codex seat's policy is decided at registration (engine codex).
    if engine != "codex" and profile == launch_process.PROFILE_SEAT and (refused := seat_refusal(policy.body)):
        return refused
    if model and not (engine == "codex" and profile == launch_process.PROFILE_SEAT) and model not in {
            row["model"] for row in model_picker.picker_rows(policy.body, profile)}:
        return "model_not_offered"
    return ""


def register(state: LocalState, device_creds: LocalState, context: SessionContext, *, profile: str, job_id: str,
             engine: str, http: httpx.Client) -> PlatformResult:
    """``/sessions/register`` as the device client."""
    # The job id names the thread the turn runs for: a work item's thread binds as its own session of the run
    # (teamwork, ``octryx:<key>``) instead of replacing the main thread's binding.
    # The platform server's "needs authentication" mark from an earlier turn would hide its tools for ~15 minutes;
    # the launcher authenticates that server itself (``mcp_auth_cache``). The platform counts each mark removed.
    cleared = mcp_auth_cache.clear(state.claude_config_dir_for(profile), launch_settings.MCP_SERVER_NAME)
    return call_control_plane(device_creds, context, "POST", "/sessions/register", http=http, timeout=TIMEOUT,
                              body={"profile": profile, "client": CLIENT_NAME, "client_version": __version__,
                                    **({"job_id": job_id} if job_id else {}),
                                    **({"engine": "codex"} if engine == "codex" else {}),
                                    **({"mcp_auth_cache_cleared": True} if cleared else {})})


def session_settings(*, shim: Path, state: LocalState, model_vars: dict[str, str], policy: PlatformResult,
                     base_url: str, profile: str, model: str, workflow_run: str,
                     contract: Any) -> tuple[dict[str, Any], str]:
    """The generated settings and, for a run's turn, the commit trailer its attribution asks for."""
    settings = launch_settings.build_settings(shim=shim, state_root=state.root, env=model_vars, policy=policy.body,
                                     base_url=base_url, profile=profile)
    trailer = ""
    if workflow_run:
        # The browser of a run phase (``browser_mcp``, only in a turn whose phase opted in): no approval prompt per
        # browser action also outside bypass; the platform's PreToolUse rules keep it on loopback.
        settings["permissions"]["allow"].append(f"mcp__{browser_mcp.SERVER_NAME}")
        # EU AI Act Art. 50(2): every commit of a run says it was written by AI.
        settings["attribution"] = launch.run_attribution(model or model_vars.get("ANTHROPIC_MODEL", ""), contract)
        trailer = settings["attribution"]["commit"]
    return settings, trailer


def child_env(*, state: LocalState, model_vars: dict[str, str], profile: str, base_url: str, session_key: str,
              workspace_id: str, workflow_run: str, shim: Path, contract: Any, folder: str) -> dict[str, str]:
    """The Claude Code child's env: the device grant for hooks, ``apiKeyHelper`` and MCP headers, headless rules."""
    env = launch.build_child_env(
        os.environ, model=model_vars, state_root=state.root, claude_config_dir=state.claude_config_dir_for(profile),
        base_url=base_url, session_key=session_key, workspace_id=workspace_id, work_item="", profile=profile,
        workflow_run=workflow_run, shim=shim,
    )
    env[CREDENTIAL_SET_ENV] = CREDENTIAL_SET_DEVICE
    workspace_prep.child_path(contract, folder, env)  # the declared environment's path first (``.venv/bin``)
    env[session_rules.ENV_SESSION_MODE] = session_rules.MODE_HEADLESS
    return env


def session_extra(*, state: LocalState, device_creds: LocalState, context: SessionContext, policy: PlatformResult,
                  settings: dict[str, Any], trailer: str, base_url: str, session_key: str, workspace_id: str,
                  workflow_run: str, shim: Path, engine: str, profile: str, seat_credential: str) -> dict[str, Any]:
    """What the drivers read besides the settings (``PreparedSession.extra``); no credential except a Codex seat's."""
    extra: dict[str, Any] = {"commit_trailer": trailer} if trailer else {}
    # What a Codex turn needs to write its own provider config (``codex_driver``); no credential in it.
    extra["gateway"] = {"base_url": base_url, "session_key": session_key, "workspace_id": workspace_id,
                        "workflow_run": workflow_run}
    extra["hook_shim"] = str(shim)
    # A turn without a model of its own runs on the device's default, like a Claude Code turn: ``codex_model`` in the
    # launcher's config, else the "main" alias.
    extra["default_model"] = str(state.config().get("codex_model") or "") or _aliases(state)["main"]
    if engine:
        extra["engine"] = engine
    if launch_sandbox.sandbox_network(policy.body) == launch_sandbox.SANDBOX_NETWORK_OPEN:
        # The sandbox's question for a host outside its lists is answered allow (``device_sdk``); the
        # platform's host stays in deniedDomains.
        extra["sandbox_network"] = launch_sandbox.SANDBOX_NETWORK_OPEN
        extra["denied_hosts"] = list(settings["sandbox"]["network"]["deniedDomains"])
    if engine == "codex" and profile == launch_process.PROFILE_SEAT:
        from .codex_seat import EXTRA_TRAFFIC, seat_traffic  # noqa: PLC0415

        # Where the seat's calls leave (the platform's ``seat_traffic``): the job's loopback seat proxy on ``device``.
        extra.update(codex_seat=True, seat_credential=seat_credential, state_root=str(state.root),
                     **{EXTRA_TRAFFIC: seat_traffic(policy.body)})
    from . import transcript_upload  # noqa: PLC0415 - its redactor imports device_sdk, which imports device_session

    if transcript_upload.enabled(policy.body):  # The Workspace's full-transcript switch is on
        extra[transcript_upload.EXTRA_KEY] = {"state": device_creds, "context": context,
                                              "config_dir": str(state.claude_config_dir_for(profile))}
    return extra
