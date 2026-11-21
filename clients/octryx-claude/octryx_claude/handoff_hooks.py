"""The handoff inside a running session (root freeze 3c).

- **``/handoff [KEY] [--to USER] [--note TEXT] [--all]``:** the UserPromptSubmit hook runs the handoff routine
  itself and blocks the prompt with the result line, so the prompt never reaches the model.
- **``handoff_now``:** when a hook answer (PostToolUse, Stop) says the session reached the handoff trigger, the
  launcher hands over every held item (``--all``) once per crossing id. The crossing is recorded before the
  routine runs, so a failure or a hang never repeats it. The user gets one line: "Allowance at 99%: your work
  was handed over (→ branch …)".
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
from pathlib import Path
from typing import Any

import httpx

from .handoff import HandoffReport, run_handoff
from .platform import PlatformResult, SessionContext
from .state import LocalState

_COMMAND = re.compile(r"^\s*/handoff(?:\s|$)")
_CROSSING = re.compile(r"^[A-Za-z0-9:._+-]{1,80}$")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # never exit inside a hook
        raise ValueError(message)


def _parser() -> _Parser:
    parser = _Parser(prog="/handoff", add_help=False)
    parser.add_argument("key", nargs="?", default="")
    parser.add_argument("--to", default="")
    parser.add_argument("--note", default="")
    parser.add_argument("--all", action="store_true")
    return parser


def is_handoff_prompt(prompt: object) -> bool:
    return isinstance(prompt, str) and bool(_COMMAND.match(prompt))


def parse_handoff_prompt(prompt: str) -> argparse.Namespace:
    """The ``/handoff`` arguments; raises ``ValueError`` for anything malformed."""
    return _parser().parse_args(shlex.split(_COMMAND.sub("", prompt, count=1)))


def prompt_output(report: HandoffReport) -> dict[str, Any]:
    """Block the prompt (it never reaches the model) and show the result."""
    return {"decision": "block", "reason": "Octryx handoff: " + report.summary()}


def run_prompt_handoff(state: LocalState, context: SessionContext, http: httpx.Client, prompt: str,
                       cwd: Path | str) -> dict[str, Any]:
    try:
        args = parse_handoff_prompt(prompt)
    except ValueError:
        return {"decision": "block",
                "reason": "Octryx handoff: usage: /handoff [KEY] [--to USER] [--note TEXT] [--all]"}
    report = run_handoff(state, context, http, cwd=cwd, key=args.key, to_user=args.to, note=args.note,
                         all_items=args.all)
    return prompt_output(report)


def _item_line(report: HandoffReport) -> str:
    parts = []
    for item in report.items:
        if item.error:
            parts.append(f"{item.key}: not handed over ({item.error})")
        else:
            target = (f"branch {item.branch}" + (" (pushed)" if item.pushed else
                                                 " (bundle on Octryx)" if item.bundle_id else ""))
            parts.append(f"{item.key} → {target if item.branch else 'handoff only'}")
    return "; ".join(parts) or "nothing was held"


def auto_handoff(state: LocalState, context: SessionContext, http: httpx.Client, result: PlatformResult,
                 cwd: Path | str) -> str:
    """Run the automatic handoff once per crossing; the user's notice line, or ``""``."""
    body = result.body if result.outcome == "ok" else {}
    crossing = body.get("handoff_crossing")
    if body.get("handoff_now") is not True or not isinstance(crossing, str) or not _CROSSING.match(crossing):
        return ""
    if not claim_crossing(state.session_dir(context.session_key), crossing):
        return ""
    report = run_handoff(state, context, http, cwd=cwd, all_items=True, poll_seconds=0)
    if crossing.startswith("requested-"):
        prefix = "A Workspace admin asked for a handoff"
    else:
        pct = body.get("handoff_trigger_pct")
        prefix = f"Allowance at {pct:g}%" if isinstance(pct, (int, float)) else "Allowance at the handoff trigger"
    if not report.ok and not report.items:
        return f"{prefix}: the automatic handoff failed ({report.error or 'nothing handed over'})"
    return f"{prefix}: your work was handed over ({_item_line(report)})"


def claim_crossing(session_dir: Path, crossing: str) -> bool:
    """judge-s4c L6: one marker file per crossing, created atomically (``O_EXCL``); only its creator hands over."""
    marker = session_dir / f"handoff-crossing-{hashlib.sha256(crossing.encode()).hexdigest()[:24]}"
    try:
        os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return False
    return True


def with_notice(output: dict[str, Any] | None, notice: str) -> dict[str, Any] | None:
    if not notice:
        return output
    if output and output.get("systemMessage"):
        return {**output, "systemMessage": f"{output['systemMessage']}\n{notice}"}
    return {**(output or {}), "systemMessage": notice}


__all__ = ["auto_handoff", "is_handoff_prompt", "parse_handoff_prompt", "run_prompt_handoff", "with_notice"]
