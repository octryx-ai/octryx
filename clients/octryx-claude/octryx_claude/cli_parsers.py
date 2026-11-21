"""The argument parsers of ``octryx-claude``: the subcommands and the session launch."""

from __future__ import annotations

import argparse

from octryx_claude import launch_process

from . import (
    analyze_cli,
    configure_cli,
    device_cli,
    handoff_cli,
    mobile_cli,
    profile_choice,
    profiles_cli,
)
from .pet import cli as pet_cli

SUBCOMMANDS = ("login", "seat-login", "status", "configure", "api-key-helper", "mcp-headers", "hook", "handoff",
               "resume", "analyze", "device", "pet", "mobile", "profiles", "context-manager", "git-credential")


def subcommand_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="octryx-claude")
    sub = parser.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login", help="sign in to Octryx in the browser")
    login.add_argument("--base-url", default="")
    login.add_argument("--workspace", default="")
    login.add_argument("--headless", action="store_true",
                       help="dev only: sign in with OCTRYX_USERNAME/OCTRYX_PASSWORD from the environment")
    login.add_argument("--seat", action="store_true",
                       help="sign the seat profile in to your own Claude subscription (no platform login)")
    sub.add_parser("seat-login", help="same as: login --seat")
    sub.add_parser("status", help="show base URL, Workspace, login state and whether seat and governed are ready")
    sub.add_parser("api-key-helper", help="print the gateway access token (Claude Code apiKeyHelper)")
    sub.add_parser("mcp-headers", help="print knowledge MCP headers (Claude Code headersHelper)")
    git_credential = sub.add_parser("git-credential", help="git credential helper inside a platform sandbox "
                                                           "(a fresh, run-bound git gateway token)")
    git_credential.add_argument("action", choices=("get", "store", "erase"))
    hook = sub.add_parser("hook", help="Claude Code hook entry point")
    hook.add_argument("event", choices=("pre-tool-use", "post-tool-use", "stop", "stop-failure", "session-end",
                                        "user-prompt-submit", "user-prompt-expansion", "pre-compact",
                                        "session-start", "post-compact"))
    context = sub.add_parser("context-manager", help="what sessions keep when they compact (on by default)")
    context.add_argument("context_action", nargs="?", choices=("on", "off", "status", "lessons"), default="status")
    context.add_argument("lessons_switch", nargs="?", choices=("on", "off"), default=None)
    handoff_cli.add_parsers(sub)
    analyze_cli.add_parser(sub)
    configure_cli.add_parser(sub)
    device_cli.add_parser(sub)
    pet_cli.add_parser(sub)
    mobile_cli.add_parser(sub)
    profiles_cli.add_parser(sub)
    return parser

def launch_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="octryx-claude",
        usage="octryx-claude [claude] [--profile auto|governed|seat] [--workspace ID|NAME] [--work-item KEY] "
              "[--no-code-intelligence] [-- <claude args>]\n"
              "       octryx-claude codex [--workspace ID|NAME] [--model ALIAS] [--work-item KEY] [-- <codex args>]\n"
              f"       octryx-claude {{{','.join(SUBCOMMANDS)}}} ...",
        description="Engines: `claude` (the default) runs Claude Code, `codex` runs OpenAI Codex CLI. Each starts only "
                    "when the Workspace allows it; `octryx status` shows the engine that applies to you. "
                    "(`octryx` is the short name of this command.)",
    )
    parser.add_argument("--profile", choices=(profile_choice.PROFILE_AUTO, *launch_process.PROFILES),
                        default=profile_choice.PROFILE_AUTO,
                        help="auto (default): seat when the Workspace allows it and the seat login exists, else "
                             "governed; governed: platform model data plane; seat: your own Claude subscription")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--work-item", default="")
    parser.add_argument("--no-code-intelligence", action="store_true",
                        help="do not bind or upload the git repository of this folder")
    return parser


__all__ = ["SUBCOMMANDS", "launch_parser", "subcommand_parser"]
