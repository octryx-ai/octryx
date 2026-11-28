"""``octryx-claude device …``: run chat requests from the platform on this device."""

from __future__ import annotations

import argparse

from . import device_state
from .device_cli_enable import run_disable, run_enable
from .device_cli_router import run_router
from .device_cli_settings import run_context, run_folders, run_live, run_logs, run_parallel, run_pause
from .device_cli_status import run_status, run_tools
from .state import LocalState


def add_parser(sub: argparse._SubParsersAction) -> None:
    device = sub.add_parser("device", help="run chat requests from Octryx on this device (background service)")
    actions = device.add_subparsers(dest="device_command", required=True)
    enable = actions.add_parser("enable", help="register this device to you and install the background service")
    enable.add_argument("--name", default="")
    enable.add_argument("--folder", action="append", default=[], help="a folder jobs may run in (repeatable)")
    enable.add_argument("--parallel", type=int, default=device_state.DEFAULT_PARALLEL_JOBS,
                        help="chats that may run here at the same time (1-8, default 6)")
    enable.add_argument("--no-service", action="store_true", help="register only; run `device run` yourself")
    actions.add_parser("disable", help="remove the service and revoke this device (your login stays)")
    actions.add_parser("status", help="registration, service, connection and limits")
    tools_parser = actions.add_parser("tools", help="the tools the launcher brings, and getting the missing ones")
    tools_parser.add_argument("--ensure", action="store_true", help="install the missing ones (pinned versions)")
    actions.add_parser("pause", help="reject new jobs and stop running ones (works offline)")
    actions.add_parser("resume", help="accept jobs again")
    folders = actions.add_parser("folders", help="the folders jobs may run in")
    folders.add_argument("folder_action", nargs="?", choices=("list", "add", "remove"), default="list")
    folders.add_argument("path", nargs="?", default="")
    folders.add_argument("--yes", action="store_true", help="add without the confirmation question")
    parallel = actions.add_parser("parallel", help="how many chats may run here at the same time (1-8)")
    parallel.add_argument("count", type=int)
    logs = actions.add_parser("logs", help="the service log")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.add_argument("-n", "--lines", type=int, default=50)
    live = actions.add_parser("live", help="let your phone list and message the Claude Code sessions running here")
    live.add_argument("live_action", nargs="?", choices=("on", "off", "status", "progress"), default="status")
    live.add_argument("progress_action", nargs="?", choices=("on", "off", "status"), default="status",
                      help="with 'progress': whether the phone sees what the sessions are doing (default on)")
    router = actions.add_parser("router", help="the local decision model that suggests a model per turn (llama.cpp)")
    router.add_argument("router_action", nargs="?", choices=("on", "off", "status", "try"), default="status")
    router.add_argument("prompt", nargs="?", default="")
    router.add_argument("--model", default="", help="qwen3-1.7b (default, Apache-2.0) or d1-2b (LFM licence)")
    router.add_argument("--accept-licence", action="store_true",
                        help="accept a restricted model's licence after reading its notice (d1-2b)")
    context = actions.add_parser("context", help="the context size Mac turns compact at (100000-300000 tokens)")
    context.add_argument("tokens", nargs="?", type=int)
    run = actions.add_parser("run", help="the background service loop (the OS service calls it)")
    run.add_argument("--runner", action="store_true",
                     help="as a platform server runner: join the pool with the installation's join secret, serve")


def run_device_command(args: argparse.Namespace, state: LocalState) -> int:
    command = args.device_command
    if command == "enable":
        return run_enable(args, state)
    if command == "disable":
        return run_disable(state)
    if command == "status":
        return run_status(state)
    if command == "tools":
        return run_tools(args, state)
    if command in ("pause", "resume"):
        return run_pause(state, command == "pause")
    if command == "folders":
        return run_folders(args, state)
    if command == "parallel":
        return run_parallel(args, state)
    if command == "logs":
        return run_logs(args, state)
    if command == "live":
        return run_live(args, state)
    if command == "router":
        return run_router(args, state)
    if command == "context":
        return run_context(args, state)
    if getattr(args, "runner", False):
        from .runner import main as runner_main  # noqa: PLC0415

        return runner_main()
    from .device_runtime import run_service

    return run_service(state)


__all__ = ["add_parser", "run_device_command"]
