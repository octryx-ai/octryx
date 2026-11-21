"""Test runs of a device run phase run outside Claude Code's sandbox, in any form (owner approved).

Inside Claude Code's sandbox Chromium cannot start ("bootstrap_check_in ... MachPortRendezvousServer: Permission
denied (1100)": the macOS sandbox profile has no mach-register, and no sandbox setting adds it), and a test's HTTP
calls to the app it started ask for ``SandboxNetworkAccess`` each time. Claude Code's ``excludedCommands`` matches
every part of a command line on its own, so
``python -m pytest -q tests/x.py 2>&1 | tail -30`` (the agents' usual form) could only be excluded together with
``tail *``, which would let ``tail`` read the launcher's credentials unsandboxed.

So the launcher's PreToolUse hook recognises a **test run** (:func:`is_test_run`) after the platform allowed it, and
hands Claude Code the same command wrapped as ``<octryx-claude> test-run <base64>`` with ``permissionDecision:
allow`` (``updatedInput``; no prompt, nobody sits at the device in a run phase). That one form is the session's
``sandbox.excludedCommands`` entry. The wrapper decodes the command, checks it again with the same rules (a model
that types the wrapper itself gets nothing more) and runs it with ``/bin/sh``. The platform and the evidence see the
command as the agent wrote it: the PostToolUse report is unwrapped first (:func:`unwrap`).

A test run is pytest (``pytest``, ``py.test``, ``<python> -m pytest``) or ``<python> -m unittest`` with any options
and selection (single files, ``-k``, ``-x``, ``--lf``), optionally behind ``timeout <duration>``, environment
assignments (never ``DYLD_*`` / ``LD_*``) and ``cd`` into the repository, joined by ``&&``, ``||``, ``;``, with
``2>&1`` / ``2>/dev/null`` and read-only stages after a pipe (``tail``, ``head``, ``grep``, ``sort``, ``uniq``,
``wc``, ``cut``, ``tr``, ``cat`` without files). No other redirection, no ``$``, no backticks, no subshell, no
background ``&``. Starting the app on 127.0.0.1 needs no exception: the sandbox allows binding local ports
(``allowLocalBinding``) and loopback calls bypass its proxy (``NO_PROXY``); the browser the tests start is the one
part that cannot run inside it.

What stays: the platform decides every command first (the hard-deny list, the phase's shell rules, the Workspace's
command safety); the sandbox still holds every other command; the test code itself is the repository's, as in the
pipeline, which has always run outside the sandbox.
"""

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
    """The environment pin and the code style's tools of this session's run contract: the same rules the hook wrapped
    the command with (``hooks.test_run_output``), so a style tool run the hook wrapped (``ruff check``,
    ``dart format``) passes the wrapper's check too. The contract file sits in the session folder, which the sandbox
    can neither read nor write."""
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
    """``octryx-claude test-run <base64>``: check the command again and run it (never returns when it runs)."""
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
    """The pipeline's environment for a command that runs a declared command (``test``, ``system_test``, a ``lint``
    step), else ``None`` (the session's own). The pipeline runs a declared command with the launcher's interpreter
    first on ``PATH`` (Playwright pinned, its browsers); the agent's run of the same command gets the same ``PATH``,
    browser default and Playwright browsers, so it sees what the pipeline sees (``/usr/bin/python3`` has no
    Playwright)."""
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
    """The run's pinned environment, else the environment file of the folder the command runs in."""
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
    """One part of ``command`` is a Playwright CLI screenshot (:func:`screenshot`)."""
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
