"""Launching Claude Code for a terminal session: open the session on the platform, then run it.

``_open_session`` checks the target, the Workspace's client policy, the profile, registers the session and
prepares its catalog skills; ``_run_session`` writes the session files, registers the hook key, starts the
hook signer, the presence heartbeat and the transcript upload, and supervises Claude Code. Messages carry
fixed reason codes only; tokens and response bodies are never printed.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from octryx_claude import launch_process, launch_settings, transcript_streams

from . import (
    analyze_cli,
    cli_session,
    engine_choice,
    launch,
    presence_heartbeat,
    profile_choice,
    seat_login,
    seat_status,
    session_rules,
    signer,
    skills,
    status_block,
    supervisor,
    transcript_upload,
    usage,
    workspace_prep,
)
from .cli_session import SHIM, engine_refusal, session_target
from .platform import PlatformResult, SessionContext, call_control_plane, safe_code, valid_header_value
from .state import LocalState

POLICY_TIMEOUT = 15.0
HOOK_KEY_TIMEOUT = 15.0
SEAT_LOGIN_NOTICE = (
    "octryx-claude: seat profile: Claude Code uses your own Claude subscription in this octryx profile only.\n"
    "octryx-claude: if Claude Code asks you to sign in, run /login there (your plain `claude` login is not used "
    "or changed).\n"
)


@dataclass
class _Session:
    """What the launch knows once the session is registered, before Claude Code starts."""

    base_url: str
    workspace_id: str
    workspace_label: str
    work_item: str
    claude: str
    context: SessionContext
    policy: PlatformResult
    profile: str
    aliases: dict[str, str]
    seat_credential: str
    delivery: object


def _client_policy(state: LocalState, context: SessionContext, workspace_label: str,
                   requested: str) -> PlatformResult | int:
    """The Workspace's client policy for this session; its notices are said once here."""
    with httpx.Client() as http:
        result = call_control_plane(
            state, context, "GET", "/client-policy", http=http, timeout=POLICY_TIMEOUT
        )
    if not status_block.policy_ok(result):
        lines = status_block.lines_for(state, result, cli_session.codes(result), workspace=workspace_label,
                                       requested=requested)
        status_block.write(sys.stderr, lines)
        return cli_session.fail(f"session not started: client policy {cli_session.codes(result)}")
    verification = result.body.get("verification")
    if isinstance(verification, dict) and safe_code(verification.get("state")) == "needs_configuration":
        sys.stderr.write("octryx-claude: warning: verification gate needs_configuration for this Workspace\n")
        # Said once here; the Stop hook stays silent while the state is unchanged.
        session_rules.record_verification_notice(state, context.session_key, "needs_configuration")
    if notice := session_rules.scope_notice(state):  # every start, one line
        sys.stderr.write(f"octryx-claude: {notice}\n")
    return result


def _choose_profile(args: argparse.Namespace, claude_args: Sequence[str], state: LocalState, claude: str,
                    result: PlatformResult, purpose: str) -> tuple[str, dict] | int:
    """The session's profile; ``--profile auto`` (the default) is decided once here for the whole session."""
    seat = status_block.seat_state_for(state, result)
    if purpose and (not_ready := analyze_cli.seat_not_ready(seat)):  # ``analyze`` runs on a ready seat only
        return cli_session.fail(f"analysis not started: {not_ready}")
    if args.profile == profile_choice.PROFILE_AUTO and seat_login.offer_login(
            state, seat, interactive=_interactive(claude_args), ask=_ask):
        if seat_login.run_seat_login(state, claude) == 0:
            seat = status_block.seat_state_for(state, result)
    return profile_choice.choose_profile(args.profile, seat=seat).profile, seat


def _open_session(args: argparse.Namespace, claude_args: Sequence[str], state: LocalState,
                  purpose: str) -> _Session | int:
    """Target, policy, profile, registration and skills of a terminal session, or the exit code of a refusal."""
    target = session_target(args, state)
    if isinstance(target, int):
        return target
    base_url, workspace_id, workspace_label = target
    if refused := engine_refusal(state, base_url, workspace_id, engine_choice.CLAUDE_CODE):
        return cli_session.fail(refused)
    config = state.config()
    work_item = str(args.work_item or config.get("work_item") or "")
    if work_item and not valid_header_value(work_item):
        return cli_session.fail("denied: work_item_invalid")
    try:
        claude = launch.resolve_claude()
    except launch.LaunchRefusedError as exc:
        return cli_session.fail(f"needs_configuration: {exc.code}")
    context = SessionContext(base_url, str(uuid.uuid4()), workspace_id, work_item)
    result = _client_policy(state, context, workspace_label, args.profile)
    if isinstance(result, int):
        return result
    chosen = _choose_profile(args, claude_args, state, claude, result, purpose)
    if isinstance(chosen, int):
        return chosen
    profile, seat = chosen
    aliases = cli_session.aliases(config)
    with httpx.Client() as http:
        usage_result = usage.fetch_usage(state, context, http=http)
    status_block.write(sys.stderr, status_block.lines_for(
        state, result, cli_session.codes(result), workspace=workspace_label, requested=args.profile,
        model=status_block.session_model(claude_args, aliases), seat=seat, usage_result=usage_result))
    if profile == launch_process.PROFILE_SEAT and (refused := seat_status.seat_refusal(result.body)):
        return cli_session.fail(f"session not started: denied: {refused} (use the governed profile)")
    seat_credential, refused = cli_session.register(state, context, profile, purpose)
    if refused:
        return cli_session.fail(f"session not started: {refused}")
    try:  # The session's catalog skills (a read-only plugin); a failed verification refuses the session
        with httpx.Client() as http:
            delivery = skills.prepare(state, context, http=http)
    except skills.SkillDeliveryRefusedError as exc:
        return cli_session.fail(f"session not started: denied: {exc.code}")
    return _Session(base_url, workspace_id, workspace_label, work_item, claude, context, result, profile, aliases,
                    seat_credential, delivery)


def _session_process(claude_args: Sequence[str], state: LocalState,
                     session: _Session) -> tuple[list[str], dict[str, str]] | int:
    """Claude Code's argv and environment for the session, with its settings and MCP files written."""
    context, profile, delivery = session.context, session.profile, session.delivery
    model = launch.model_env(
        base_url=session.base_url, session_key=context.session_key, workspace_id=session.workspace_id,
        work_item=session.work_item, aliases=session.aliases, seat_credential=session.seat_credential,
    )
    settings = launch_settings.build_settings(shim=SHIM, state_root=state.root, env=model, policy=session.policy.body,
                                     base_url=session.base_url, profile=profile, plugin_dir=delivery.plugin_dir)
    mcp = launch_settings.build_mcp_config(shim=SHIM, base_url=session.base_url, catalog_servers=delivery.mcp_servers)
    settings_path, mcp_path = launch_process.write_session_files(state.session_dir(context.session_key), settings, mcp)
    try:
        argv = launch_process.build_claude_argv(
            session.claude, settings_path=settings_path, mcp_path=mcp_path,
            session_key=context.session_key, user_args=claude_args, plugin_dir=delivery.plugin_dir,
        )
    except launch.LaunchRefusedError as exc:
        return cli_session.fail(f"denied: {exc.code} ({exc.detail})")
    env = launch.build_child_env(
        os.environ, model=model, state_root=state.root, claude_config_dir=state.claude_config_dir_for(profile),
        base_url=session.base_url, session_key=context.session_key, workspace_id=session.workspace_id,
        work_item=session.work_item, profile=profile, shim=SHIM,
    )
    # In a -p/--print run the board hints never block a stop.
    env[session_rules.ENV_SESSION_MODE] = (session_rules.MODE_HEADLESS if session_rules.headless_session(claude_args)
                                           else session_rules.MODE_INTERACTIVE)
    if refused := workspace_prep.prepare_terminal(state, context, os.getcwd(), env):  # the run's branch + environment
        return cli_session.fail(f"session not started: {refused}")
    return argv, env


def _run_session(args: argparse.Namespace, claude_args: Sequence[str], state: LocalState, session: _Session) -> int:
    """Start Claude Code for an opened session and wait for it; the exit code is the session's."""
    process = _session_process(claude_args, state, session)
    if isinstance(process, int):
        return process
    argv, env = process
    context, profile, session_key = session.context, session.profile, session.context.session_key
    if profile == launch_process.PROFILE_SEAT and state.first_use("seat-login-notice"):
        sys.stderr.write(SEAT_LOGIN_NOTICE)
    sys.stderr.write(
        f"octryx-claude: session {session_key} | profile {profile} | workspace {session.workspace_label} | "
        f"{session.base_url} | policy {launch.policy_summary(session.policy.body)} | {session.delivery.summary()}\n"
    )
    sys.stderr.flush()
    # The hook key lives only in this process: never in a file, env var, argv or log.
    hook_key = signer.new_hook_key()
    with httpx.Client() as http:
        registered = call_control_plane(
            state, context, "POST", "/sessions/hook-key", http=http, timeout=HOOK_KEY_TIMEOUT,
            body={"hook_key": signer.encode_hook_key(hook_key), "state_root": str(state.root)},
        )
    if registered.outcome != "ok" or registered.state != "registered":
        return cli_session.fail(f"session not started: hook key {cli_session.codes(registered)}")
    cli_session.code_intelligence(args, state, context)
    try:
        hook_signer = signer.start_signer(state, session_key, hook_key)
    except signer.SignerUnavailableError as exc:
        return cli_session.fail(f"session not started: hook signer {exc.code}")
    # Octryx Mobile: the heartbeat keeps this session listed on the person's phone while Claude Code runs.
    # With the Workspace's switch on, the full transcript goes to the platform alongside.
    transcripts = transcript_upload.running(
        state, context, config_dir=state.claude_config_dir_for(profile),
        on=transcript_upload.enabled(session.policy.body),
        claude_session_id=transcript_streams.claude_session_for(session_key, list(claude_args)))
    with hook_signer, presence_heartbeat.running(state, context), transcripts:
        try:
            code = supervisor.supervise(argv, env)
        except OSError:
            return cli_session.fail("session not started: claude_not_startable")
    # A rejected subscription login or a reached limit is said here with its fix (``seat_status``).
    if profile == launch_process.PROFILE_SEAT and seat_status.finish_seat_session(state, session_key, code, sys.stderr):
        profile_choice.mark_seat_session_ok(state)  # the seat login works: auto may pick seat next time
    return code


def _launch(args: argparse.Namespace, claude_args: Sequence[str], state: LocalState, purpose: str = "") -> int:
    session = _open_session(args, claude_args, state, purpose)
    if isinstance(session, int):
        return session
    return _run_session(args, claude_args, state, session)


def _ask(prompt: str) -> str:
    sys.stderr.write(prompt)
    sys.stderr.flush()
    return sys.stdin.readline()


def _interactive(claude_args: Sequence[str]) -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty() and not session_rules.headless_session(claude_args)
