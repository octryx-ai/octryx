"""``octryx codex``: Codex CLI in the terminal, governed like ``octryx claude``."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Sequence
from types import SimpleNamespace

import httpx

from . import (
    cli_session,
    codex_driver,
    codex_seat,
    engine_choice,
    launch,
    launch_process,
    presence_heartbeat,
    signer,
    status_block,
    supervisor,
    workspace_prep,
)
from .cli_session import SHIM, engine_refusal, session_target
from .platform import SessionContext, call_control_plane
from .state import LocalState

REFUSED_ARGS = ("--dangerously-bypass-approvals-and-sandbox", "--yolo", "-c", "--config", "--profile", "-p",
                "--oss", "--local-provider", "--ignore-rules")


def parser() -> argparse.ArgumentParser:
    built = argparse.ArgumentParser(prog="octryx codex",
                                    usage="octryx codex [--workspace ID|NAME] [--model ALIAS] [-- <codex args>]")
    built.add_argument("--workspace", default="")
    built.add_argument("--work-item", default="")
    built.add_argument("--model", default="", help="a model alias the Workspace admits (default: the main alias)")
    built.add_argument("--profile", choices=("governed", "seat"), default="governed",
                       help="governed (default): the Workspace's models; seat: your own ChatGPT login")
    return built


def refused_arg(codex_args: Sequence[str]) -> str:
    for arg in codex_args:
        name = arg.split("=", 1)[0]
        if name in REFUSED_ARGS:
            return name
    return ""


def seat_command(argv: Sequence[str], state: LocalState) -> int | None:
    if argv[:1] not in (["login"], ["status"]):
        return None
    try:
        codex = codex_driver.resolve_codex()
    except codex_driver.CodexUnavailableError as exc:
        return cli_session.fail(exc.hint())
    if argv[0] == "login":
        sys.stderr.write("octryx: Codex's own login for your ChatGPT account (the launcher never sees the token)\n")
        return codex_seat.login(codex, state.root, device_auth="--device-auth" in argv[1:])
    seat = "logged in" if codex_seat.logged_in(codex, state.root) else "not logged in (run: octryx codex login)"
    print(f"codex:      {codex}\nseat login: {seat}")
    return 0


def run(argv: Sequence[str], state: LocalState) -> int:
    handled = seat_command(argv, state)
    if handled is not None:
        return handled
    own, codex_args = list(argv), []
    if "--" in own:
        split = own.index("--")
        own, codex_args = own[:split], own[split + 1:]
    args = parser().parse_args(own)
    if bad := refused_arg(codex_args):
        return cli_session.fail(
            f"denied: flag_not_allowed ({bad}: the platform sets Codex's provider, config and sandbox)")
    opened = _open_session(args, state)
    if isinstance(opened, int):
        return opened
    codex, context, prepared, label = opened
    return _run_session(state, codex, context, prepared, label, codex_args)


def _open_session(args: argparse.Namespace,
                  state: LocalState) -> tuple[str, SessionContext, SimpleNamespace, str] | int:
    target = session_target(args, state)
    if isinstance(target, int):
        return target
    base_url, workspace_id, label = target
    if refused := engine_refusal(state, base_url, workspace_id, engine_choice.CODEX):
        return cli_session.fail(refused)
    try:
        codex = codex_driver.resolve_codex()
    except codex_driver.CodexUnavailableError as exc:
        return cli_session.fail(exc.hint())
    work_item = str(args.work_item or state.config().get("work_item") or "")
    session_key = str(uuid.uuid4())
    context = SessionContext(base_url, session_key, workspace_id, work_item)
    with httpx.Client() as http:
        policy = call_control_plane(state, context, "GET", "/client-policy", http=http, timeout=15.0)
    if not status_block.policy_ok(policy):
        return cli_session.fail(f"session not started: client policy {cli_session.codes(policy)}")
    profile = args.profile
    if profile == "seat":
        from .codex_seat import logged_in  # noqa: PLC0415

        if not logged_in(codex, state.root):
            return cli_session.fail("needs_configuration: codex_seat_not_logged_in (run: octryx codex login)")
    credential, refused = cli_session.register(state, context, profile, engine="codex")
    if refused:
        return cli_session.fail(f"session not started: {refused}")
    env = launch.build_child_env(
        os.environ, model={}, state_root=state.root,
        claude_config_dir=state.claude_config_dir_for(launch_process.PROFILE_GOVERNED),
        base_url=base_url, session_key=session_key, workspace_id=workspace_id, work_item=work_item, profile=profile,
        shim=SHIM)
    if refused := workspace_prep.prepare_terminal(state, context, os.getcwd(), env):
        return cli_session.fail(f"session not started: {refused}")
    return codex, context, _prepared(args, state, context, env, credential), label


def _prepared(args: argparse.Namespace, state: LocalState, context: SessionContext, env: dict[str, str],
              credential: str) -> SimpleNamespace:
    profile, session_key = args.profile, context.session_key
    folder = state.session_dir(session_key)
    folder.mkdir(parents=True, exist_ok=True)
    # The seat uses Codex's own default model unless one is named; governed the Workspace alias of the device.
    model = args.model or ("" if profile == "seat" else
                           str(state.config().get("codex_model") or "") or cli_session.aliases(state.config())["main"])
    return SimpleNamespace(
        session_key=session_key, model=model, profile=profile, settings_path=folder / "settings.json", env=env,
        extra={**({"codex_seat": True, "seat_credential": credential, "state_root": str(state.root)}
                  if profile == "seat" else {}),
               "gateway": {"base_url": context.base_url, "session_key": session_key,
                           "workspace_id": context.workspace_id, "workflow_run": ""}, "hook_shim": str(SHIM)})


def _run_session(state: LocalState, codex: str, context: SessionContext, prepared: SimpleNamespace, label: str,
                 codex_args: Sequence[str]) -> int:
    session_key, profile, model, base_url = context.session_key, prepared.profile, prepared.model, context.base_url
    hook_key = signer.new_hook_key()  # in this process only: never in a file, env var, argv or log
    with httpx.Client() as http:
        keyed = call_control_plane(state, context, "POST", "/sessions/hook-key", http=http, timeout=15.0,
                                   body={"hook_key": signer.encode_hook_key(hook_key), "state_root": str(state.root)})
    if keyed.outcome != "ok" or keyed.state != "registered":
        return cli_session.fail(f"session not started: hook key {cli_session.codes(keyed)}")
    try:
        hook_signer = signer.start_signer(state, session_key, hook_key)
    except signer.SignerUnavailableError as exc:
        return cli_session.fail(f"session not started: hook signer {exc.code}")
    shown = f"{profile}{' (your ChatGPT login)' if profile == 'seat' else ''}"
    sys.stderr.write(f"octryx: session {session_key} | engine Codex | profile {shown}"
                     f" | model {model or 'Codex default'} | workspace {label} | {base_url}\n")
    sys.stderr.flush()
    with hook_signer, presence_heartbeat.running(state, context):
        home = codex_driver.prepare_home(prepared, sandboxed=True, interactive=True)
        try:
            return supervisor.supervise([codex, "--dangerously-bypass-hook-trust", *codex_args],
                                        codex_driver.environment(prepared, home))
        except OSError:
            return cli_session.fail("session not started: codex_not_startable")


__all__ = ["parser", "refused_arg", "run"]
