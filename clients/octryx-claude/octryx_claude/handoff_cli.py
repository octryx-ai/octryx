"""``octryx-claude handoff`` and ``octryx-claude resume`` in a plain terminal with the user's Octryx login.
No running session, model or seat allowance is needed."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx

from .handoff import run_handoff
from .handoff_resume import run_resume
from .platform import SessionContext, valid_header_value
from .state import LocalState

ENV_SESSION_KEY = "OCTRYX_SESSION_KEY"
ENV_WORK_ITEM = "OCTRYX_WORK_ITEM"


def add_parsers(sub: argparse._SubParsersAction) -> None:
    handoff = sub.add_parser("handoff", help="hand your work over (WIP branch or bundle, handoff, takeover)")
    handoff.add_argument("key", nargs="?", default="")
    handoff.add_argument("--to", default="", help="the user who should take over")
    handoff.add_argument("--note", default="")
    handoff.add_argument("--all", action="store_true", help="every item your agents hold in this Workspace")
    handoff.add_argument("--workspace", default="")
    resume = sub.add_parser("resume", help="check out a handed-over work item and continue it")
    resume.add_argument("key")
    resume.add_argument("--workspace", default="")
    resume.add_argument("--no-start", action="store_true", help="only check out; do not start a session")


def cli_context(state: LocalState, workspace: str, environ: dict[str, str] | None = None) -> SessionContext | str:
    source = os.environ if environ is None else environ
    config = state.config()
    base_url = str(config.get("base_url") or "").rstrip("/")
    if not base_url or state.credentials().get("base_url") != base_url:
        return "needs_configuration: not_logged_in (run: octryx-claude login --base-url URL)"
    workspace_id = str(workspace or source.get("OCTRYX_WORKSPACE_ID") or config.get("workspace_id") or "")
    if not workspace_id or not valid_header_value(workspace_id):
        return "needs_configuration: workspace_not_selected (pass --workspace ID)"
    try:
        session_key = str(uuid.UUID(str(source.get(ENV_SESSION_KEY) or "")))
    except ValueError:
        session_key = str(uuid.uuid4())
    work_item = str(source.get(ENV_WORK_ITEM) or "")
    return SessionContext(base_url, session_key, workspace_id, work_item if valid_header_value(work_item) else "")


def run_handoff_command(args: argparse.Namespace, state: LocalState, *, cwd: Path | None = None) -> int:
    context = cli_context(state, args.workspace)
    if isinstance(context, str):
        sys.stderr.write(f"octryx-claude: {context}\n")
        return 2
    with httpx.Client() as http:
        report = run_handoff(state, context, http, cwd=cwd or Path.cwd(), key=args.key, to_user=args.to,
                             note=args.note, all_items=args.all)
    for line in report.lines() or ["Nothing to hand over."]:
        sys.stdout.write(f"octryx-claude: {line}\n")
    return 0 if report.ok else 1


def run_resume_command(
    args: argparse.Namespace, state: LocalState, *, launch: Callable[[Sequence[str]], int], cwd: Path | None = None
) -> int:
    context = cli_context(state, args.workspace)
    if isinstance(context, str):
        sys.stderr.write(f"octryx-claude: {context}\n")
        return 2
    with httpx.Client() as http:
        result = run_resume(state, context, http, key=args.key, cwd=cwd or Path.cwd())
    if result.error:
        sys.stderr.write(f"octryx-claude: resume failed: {result.error}\n")
        return 1
    sys.stdout.write(f"octryx-claude: {args.key} checked out at {result.path} ({result.commit[:12]})\n")
    if args.no_start:
        return 0
    os.chdir(result.path)
    return launch(["--workspace", context.workspace_id, "--work-item", args.key, "--",
                   "--append-system-prompt", result.opening_context])


__all__ = ["add_parsers", "cli_context", "run_handoff_command", "run_resume_command"]
