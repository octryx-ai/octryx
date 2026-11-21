"""``octryx-claude login --seat`` (alias ``seat-login``): the seat profile signs in to your own Claude subscription.

Runs ``claude auth login --claudeai`` (Claude Code's own login command) with ``CLAUDE_CONFIG_DIR`` pointing at
``claude-config-seat/``, so the subscription login lands in the seat profile only: plain ``claude`` and ``~/.claude*``
stay untouched (G1), and the launcher never sees or reads the credential. The platform login is not needed. The
child gets no ``ANTHROPIC_*`` variable and no provider switch, so the login talks to Anthropic directly.

On success the launcher writes its seat marker and clears a stored seat problem, so ``--profile auto`` picks seat
again. In ``--profile auto`` with a Workspace that allows seat but no working seat login, an interactive start asks
once per seat state (``offer_login``); a non-interactive start only prints the hint.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from typing import TextIO

from octryx_claude import launch_process

from . import launch, profile_choice, seat_status
from .platform import ENV_BASE_URL, ENV_PROFILE, ENV_SESSION_KEY, ENV_WORK_ITEM, ENV_WORKSPACE_ID
from .state import LocalState, read_json, write_private_json

LOGIN_ARGS = ("auth", "login", "--claudeai")
DECLINED_FILE = ".seat-login-declined"
OFFERED_STATES = (seat_status.STATE_NOT_LOGGED_IN, seat_status.STATE_LOGIN_EXPIRED)
PROMPT = "octryx-claude: Seat (your Claude subscription) is not logged in. Log in now? [y/N] "
_OCTRYX_SESSION_ENV = (ENV_BASE_URL, ENV_SESSION_KEY, ENV_WORK_ITEM, ENV_WORKSPACE_ID, ENV_PROFILE)


def login_env(parent: Mapping[str, str], state: LocalState) -> dict[str, str]:
    dropped = set(launch.SCRUBBED_ENV) | set(launch.PROVIDER_SWITCHES) | set(_OCTRYX_SESSION_ENV)
    env = {key: value for key, value in parent.items() if key not in dropped and not key.startswith("ANTHROPIC_")}
    env["CLAUDE_CONFIG_DIR"] = str(state.claude_config_dir_for(launch_process.PROFILE_SEAT))
    return env


def run_seat_login(state: LocalState, claude: str, *, out: TextIO | None = None) -> int:
    """Claude Code's own subscription login in the seat config dir; ``0`` when it succeeded."""
    stream = out or sys.stderr
    stream.write(f"octryx-claude: seat login: signing in to your Claude subscription in "
                 f"{state.claude_config_dir_for(launch_process.PROFILE_SEAT)} (your plain `claude` login is not used "
                 f"or changed)\n")
    stream.flush()
    try:
        code = subprocess.run([claude, *LOGIN_ARGS], env=login_env(os.environ, state), check=False).returncode
    except OSError:
        stream.write("octryx-claude: seat login failed: claude_not_startable\n")
        return 2
    if code != 0:
        stream.write(f"octryx-claude: seat login failed (claude exit {code}); try again with "
                     f"`{seat_status.SEAT_LOGIN_COMMAND}`, or start `octryx-claude --profile seat` and run /login\n")
        return code
    profile_choice.mark_seat_session_ok(state)
    seat_status.clear_problem(state)
    with contextlib.suppress(FileNotFoundError):
        (state.root / DECLINED_FILE).unlink()
    stream.write("octryx-claude: seat login done; --profile auto now uses your subscription where the Workspace "
                 "allows it\n")
    return 0


def offer_login(state: LocalState, seat: seat_status.SeatState, *, interactive: bool,
                ask: Callable[[str], str]) -> bool:
    """``True`` when the user wants to log in now. Asked once per seat state; never without a terminal."""
    if seat.code not in OFFERED_STATES or not interactive:
        return False
    if read_json(state.root / DECLINED_FILE).get("state") == seat.code:
        return False
    try:
        answer = ask(PROMPT)
    except (EOFError, OSError):
        answer = ""
    if answer.strip().lower() in ("y", "yes"):
        return True
    write_private_json(state.root / DECLINED_FILE, {"state": seat.code})
    return False


__all__ = ["LOGIN_ARGS", "PROMPT", "login_env", "offer_login", "run_seat_login"]
