"""Command dispatch for ``octryx-claude``.
Messages carry fixed reason codes only; tokens, passwords and response bodies are never printed."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import httpx

from octryx_claude import post_tool_use_hook, pre_tool_use_hook, session_hooks

from . import (
    analyze_cli,
    cli_account,
    cli_launch,
    cli_parsers,
    configure_cli,
    device_cli,
    engine_choice,
    handoff_cli,
    hooks,
    mobile_cli,
    profiles_cli,
    seat_hooks,
    skill_hooks,
)
from .cli_parsers import SUBCOMMANDS
from .pet import cli as pet_cli
from .pet.account import LocalAccount
from .state import LocalState

# The subcommands and session steps live in ``cli_account``, ``cli_launch``, ``cli_parsers`` and ``cli_session``.


def _hook(args: argparse.Namespace, state: LocalState) -> int:
    runner = {
        "pre-tool-use": pre_tool_use_hook.run_pre_tool_use,
        "post-tool-use": post_tool_use_hook.run_post_tool_use,
        "stop": hooks.run_stop,
        "stop-failure": lambda state, http: seat_hooks.run_stop_failure(state),
        "session-end": session_hooks.run_session_end,
        "user-prompt-submit": session_hooks.run_user_prompt_submit,
        "user-prompt-expansion": skill_hooks.run_user_prompt_expansion,
        "pre-compact": session_hooks.run_pre_compact,
        "session-start": session_hooks.run_session_start,
        "post-compact": session_hooks.run_post_compact,
    }[args.event]
    with httpx.Client() as http:
        return runner(state, http)


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list[:1] == ["test-run"]:
        from .local_tests import run_wrapped  # noqa: PLC0415 - a test run outside the sandbox (``local_tests``)

        return run_wrapped(args_list[1:])
    if args_list[:1] == ["l10n-merge"]:
        from .l10n_merge import main as l10n_merge  # noqa: PLC0415 - no login, no state: a repository build step

        return l10n_merge(args_list[1:])
    state = LocalState().ensure()
    # ``octryx claude ...`` is the default launch; ``octryx codex ...`` runs Codex CLI (``codex_cli``).
    if args_list[:1] == [engine_choice.CODEX]:
        from . import codex_cli  # noqa: PLC0415

        return codex_cli.run(args_list[1:], state)
    if args_list[:1] == ["claude"]:
        args_list = args_list[1:]
    if args_list and args_list[0] in SUBCOMMANDS:
        args = cli_parsers.subcommand_parser().parse_args(args_list)
        if args.command == "login":
            return cli_account.login_command(args, state)
        if args.command == "seat-login":
            return cli_account.seat_login_command(state)
        if args.command == "status":
            return cli_account.status_command(state)
        if args.command == "configure":
            return configure_cli.run_configure_command(args, state)
        if args.command == "api-key-helper":
            return cli_account.api_key_helper(state)
        if args.command == "mcp-headers":
            return cli_account.mcp_headers(state)
        if args.command == "device":
            return device_cli.run_device_command(args, state)
        if args.command == "pet":
            return pet_cli.run_pet_command(args, LocalAccount(state))
        if args.command == "mobile":
            return mobile_cli.run_mobile_command(args, state)
        if args.command == "profiles":
            return profiles_cli.run_profiles_command(args, state)
        if args.command == "context-manager":
            return cli_account.context_manager_command(args, state)
        if args.command == "handoff":
            return handoff_cli.run_handoff_command(args, state)
        if args.command == "resume":
            return handoff_cli.run_resume_command(args, state, launch=main)
        if args.command == "analyze":
            def launch_session(session: object, claude_args: list[str]) -> int:
                return cli_launch._launch(session, claude_args, state, purpose=analyze_cli.PURPOSE)

            return analyze_cli.run_analyze_command(args, state, launch_session=launch_session)
        return _hook(args, state)
    own, claude_args = args_list, []
    if "--" in args_list:
        split = args_list.index("--")
        own, claude_args = args_list[:split], args_list[split + 1:]
    return cli_launch._launch(cli_parsers.launch_parser().parse_args(own), claude_args, state)


__all__ = [
    "main",
]
