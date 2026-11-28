"""Test runs of a device run phase run outside Claude Code's sandbox, where Chromium cannot start, through a
wrapper that is the session's only ``excludedCommands`` entry."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .local_tests_forms import (
    is_test_run,
    style_tools,
)
from .local_tests_screens import (
    screenshot,
)
from .local_tests_words import (
    ENVIRONMENT_FILE,
    WRAPPER_VERB,
    _segments,
    _strip_prefixes,
    _tokens,
    declared_runner,
    unwrap,
)

REFUSED_EXIT = 126


# macOS has no ``timeout`` (GNU coreutils), yet a test run may start with ``timeout <duration>`` (the agents' usual
# form, allowed by :func:`_strip_prefixes`). Without it, ``timeout 550 python -m pytest ... 2>&1 | grep ...`` prints
# nothing: bash's "timeout: command not found" goes through ``2>&1`` into grep, which drops it. When ``timeout``
# is missing, the wrapper's shell gets one: Homebrew's ``gtimeout`` when installed, else the command runs without a
# deadline (the platform's turn watchdog still ends a run that hangs).
TIMEOUT_FALLBACK = (
    "command -v timeout >/dev/null 2>&1 || timeout() {\n"
    '  while [ "${1#-}" != "$1" ]; do case "$1" in -s|-k|--signal|--kill-after) shift 2;; *) shift;; esac; done\n'
    '  _octryx_duration="$1"; shift\n'
    '  if command -v gtimeout >/dev/null 2>&1; then gtimeout "$_octryx_duration" "$@"; else "$@"; fi\n'
    "}"
)


def _session_rules() -> tuple[dict[str, Any] | None, list[tuple[list[str], bool]]]:
    from .local_policy import CONTRACT_FILE, session_dir  # noqa: PLC0415 - stdlib only, no httpx

    folder = session_dir()
    if folder is None:
        return None, []
    try:
        contract = json.loads((folder / CONTRACT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, []
    if not isinstance(contract, dict):
        return None, []
    pinned = contract.get("environment_pin") if isinstance(contract.get("environment_pin"), dict) else None
    return pinned, style_tools(contract)


def run_wrapped(args: Sequence[str]) -> int:
    command = None
    if len(args) == 1:
        command = unwrap(f"octryx-claude {WRAPPER_VERB} {args[0]}")
    pinned, tools = _session_rules()
    if command is None or not is_test_run(command, os.getcwd(), pinned, tools):
        sys.stderr.write("octryx-claude: test-run refused: only a test run (pytest, unittest or the repository's "
                         "declared test command, optionally piped into a reader) runs this way\n")
        return REFUSED_EXIT
    sys.stdout.flush()
    # bash where it exists: ``${PIPESTATUS[0]}`` is bash's (macOS's /bin/sh is bash; Linux's often is dash).
    shell = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"
    if takes_screenshot(command, os.getcwd()):
        return _run_with_deadline([shell, "-c", f"{TIMEOUT_FALLBACK}\n{command}"], SCREENSHOT_SECONDS)
    env = declared_env(command, os.getcwd(), pinned)
    if env is None:
        os.execv(shell, [shell, "-c", f"{TIMEOUT_FALLBACK}\n{command}"])
    else:
        os.execve(shell, [shell, "-c", f"{TIMEOUT_FALLBACK}\n{command}"], env)
    return REFUSED_EXIT  # not reached


def declared_env(command: str, root: str, pinned: dict[str, Any] | None = None) -> dict[str, str] | None:
    tokens = _tokens(command)
    segments = _segments(tokens) if tokens else None
    if not segments or not any(
            declared_runner(_strip_prefixes(raw) or [], root, pinned) for _, raw in segments):
        return None
    environment = _environment_of(root, pinned)
    from . import tools  # noqa: PLC0415 - stdlib only, no httpx

    env = tools.command_env(Path(root), [str(item) for item in environment.get("path") or [] if item], environment)
    env.setdefault(tools.BROWSERS_ENV, str(tools.browsers_path(tools.default_root())))
    return env


def _environment_of(root: str, pinned: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(pinned, dict) and isinstance(pinned.get("environment"), dict):
        return pinned["environment"]
    try:
        with open(os.path.join(root, ENVIRONMENT_FILE), encoding="utf-8") as handle:
            data = json.loads(handle.read(64_000))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# A screenshot outside the sandbox opens one page; it never runs longer than this ("Timeout").
# Playwright's CLI starts a fresh browser with a throw-away profile each time (``--user-data-dir``/``--load-storage``
# are refused above), so nothing of one run reaches the next.
SCREENSHOT_SECONDS = 120
DEADLINE_EXIT = 124


def takes_screenshot(command: str, root: str = "") -> bool:
    tokens = _tokens(command)
    segments = _segments(tokens) if tokens else None
    return any(screenshot(_strip_prefixes(raw) or [], root) for _, raw in segments or [])


def _run_with_deadline(args: list[str], seconds: float) -> int:
    process = subprocess.Popen(args, start_new_session=True)
    try:
        return process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        sys.stderr.write(f"octryx-claude: the screenshot did not finish within {seconds} s and was stopped\n")
        return DEADLINE_EXIT


__all__ = [
    "run_wrapped",
    "takes_screenshot",
]
