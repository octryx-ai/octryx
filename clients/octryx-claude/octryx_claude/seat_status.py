"""What the launcher knows about the ``seat`` profile, without reading any credential.

Seat states, the first that holds wins:

- ``unknown``: the Workspace's client policy could not be read;
- ``forbidden``: the client policy does not allow seat (with its fixed reason);
- ``login_expired``: a seat turn ended with Claude Code's ``authentication_failed`` (or ``oauth_org_not_allowed``);
- ``not_logged_in``: no sign of the subscription login (``profile_choice.seat_logged_in``, presence only);
- ``limit_reached``: a seat turn ended with ``rate_limit`` or ``billing_error`` within the last five hours;
- ``ready``.

Where a failure comes from: Claude Code's ``StopFailure`` hook ("fires instead of Stop when an API error ended the
turn"; its output is ignored) carries the fixed ``error`` code. The hook records it for the session and, for a
subscription problem, in ``.seat-problem.json``. The next prompt of the session shows it once (``UserPromptSubmit``
``systemMessage``), the launcher prints it again when the session ends, and the next start's status block and
``--profile auto`` use it. A completed seat turn (``Stop``) or ``octryx-claude login --seat`` clears it.

A refusal by the Octryx seat route is told apart by the gateway's fixed message prefix
``Octryx gateway: <state> (<reason>)``: that is not a subscription problem.

**A device turn's limit** (coordinator structured signals only): a run turn that ended on the
account's limit reports a fixed code as ``turn_finished.error`` (:func:`turn_limit_code` for Claude Code's result
``error``, :func:`codex_limit_code` for Codex's error event), so the platform never has to read the model's text for
it. Only what the engine reported counts: an agent's sentence that mentions "rate limit" is not a limit.
"""

from __future__ import annotations

import contextlib
import re
import time
from dataclasses import dataclass
from typing import Any, TextIO

from .platform import safe_code
from .state import LocalState, read_json, write_private_json

PROBLEM_FILE = ".seat-problem.json"
SESSION_FAILURE_FILE = "seat_failure.json"
LIMIT_WINDOW_SECONDS = 5 * 3600  # the subscription's shortest usage window

KIND_LOGIN_EXPIRED = "login_expired"
KIND_LIMIT_REACHED = "limit_reached"
KIND_PLATFORM_REFUSED = "platform_refused"
AUTH_ERRORS = frozenset({"authentication_failed", "oauth_org_not_allowed"})
LIMIT_ERRORS = frozenset({"rate_limit", "billing_error"})
#: The fixed codes a device turn reports as ``turn_finished.error`` when the account's limit ended it (the platform's
#: ``seat_quota.LIMIT_CODES``).
TURN_LIMIT_CODES = frozenset({"rate_limit", "billing_error", "usage_limit"})
# Codex's own error kinds and its account message ("You've hit your usage limit. Upgrade to Pro … or try again in …").
_CODEX_LIMIT_KINDS = {"usage_limit_reached": "usage_limit", "usage_limit_exceeded": "usage_limit",
                      "rate_limit_exceeded": "rate_limit", "rate_limit": "rate_limit", "usage_limit": "usage_limit"}
_CODEX_LIMIT_MESSAGE = "you've hit your usage limit"
_HTTP_429 = re.compile(r"\b429\b.*too many requests|too many requests.*\b429\b", re.IGNORECASE)
_GATEWAY_REFUSAL = re.compile(r"(?:Octryx|Octryx) gateway: ([a-z_]{1,64}) \(([a-z0-9_]{1,64})\)")
_MAX_DETAIL_CHARS = 4000

SEAT_LOGIN_COMMAND = "octryx-claude login --seat"
NO_LOGIN_RECORDED = (f"no login recorded by this launcher (run: {SEAT_LOGIN_COMMAND}; a Claude login made outside "
                     "it, e.g. in the macOS Keychain, is not visible here)")
GOVERNED_COMMAND = "octryx-claude --profile governed"

STATE_UNKNOWN = "unknown"
STATE_FORBIDDEN = "forbidden"
STATE_LOGIN_EXPIRED = "login_expired"
STATE_NOT_LOGGED_IN = "not_logged_in"
STATE_LIMIT_REACHED = "limit_reached"
STATE_READY = "ready"


@dataclass(frozen=True)
class SeatFailure:
    kind: str  # login_expired | limit_reached | platform_refused
    code: str  # Claude Code's error code, or the gateway's state/reason
    at: float = 0.0


@dataclass(frozen=True)
class SeatState:
    code: str
    label: str
    reason: str = ""  # the Workspace's fixed reason when forbidden


def _clock(at: float) -> str:
    return time.strftime("%H:%M", time.localtime(at))


def classify_failure(hook_input: dict[str, Any], *, now: float | None = None) -> SeatFailure | None:
    """A ``StopFailure`` hook input → the seat failure it means, or ``None`` (overloaded, server errors, ...)."""
    at = time.time() if now is None else now
    error = safe_code(hook_input.get("error"))
    text = " ".join(
        str(hook_input.get(key) or "")[:_MAX_DETAIL_CHARS] for key in ("error_details", "last_assistant_message")
    )
    refused = _GATEWAY_REFUSAL.search(text)
    if refused:
        return SeatFailure(KIND_PLATFORM_REFUSED, f"{refused.group(1)}/{refused.group(2)}", at)
    if error in AUTH_ERRORS:
        return SeatFailure(KIND_LOGIN_EXPIRED, error, at)
    if error in LIMIT_ERRORS:
        return SeatFailure(KIND_LIMIT_REACHED, error, at)
    return None


def turn_limit_code(error: object) -> str:
    """Claude Code's result/assistant ``error`` of a turn → its limit code, ``""`` for any other error."""
    code = safe_code(error)
    return code if code in TURN_LIMIT_CODES else ""


def codex_limit_code(row: dict[str, Any]) -> str:
    """A ``codex exec --json`` ``error`` / ``turn.failed`` line → ``usage_limit`` / ``rate_limit``, else ``""``.

    Codex's error kind when it sends one, its exact account message, or an HTTP 429 in the error it reports; never
    the agent's own text (that comes as ``item.completed`` agent messages, not as an error line)."""
    if row.get("type") not in ("error", "turn.failed"):
        return ""
    error = row.get("error") if isinstance(row.get("error"), dict) else {}
    for kind in (error.get("type"), error.get("code"), row.get("code")):
        mapped = _CODEX_LIMIT_KINDS.get(safe_code(kind))
        if mapped:
            return mapped
    message = " ".join(str(error.get("message") or row.get("message") or "")[:_MAX_DETAIL_CHARS].split())
    if message.replace("\u2019", "'").lower().startswith(_CODEX_LIMIT_MESSAGE):
        return "usage_limit"
    return "rate_limit" if _HTTP_429.search(message) else ""


def failure_message(failure: SeatFailure) -> str:
    """The explicit message with the fix; fixed codes only."""
    if failure.kind == KIND_LOGIN_EXPIRED:
        return (f"seat: your Claude subscription login was rejected ({failure.code}). Fix: run /login in this "
                f"session or `{SEAT_LOGIN_COMMAND}`, or restart with `{GOVERNED_COMMAND}`.")
    if failure.kind == KIND_LIMIT_REACHED:
        return (f"seat: your Claude subscription limit is reached ({failure.code}, at {_clock(failure.at)}). "
                f"Wait for the reset Claude Code shows, or restart with `{GOVERNED_COMMAND}`.")
    return (f"seat: Octryx refused the seat call ({failure.code}). "
            f"Start a new session, or restart with `{GOVERNED_COMMAND}`.")


def _failure_from(payload: dict[str, Any]) -> SeatFailure | None:
    kind = safe_code(payload.get("kind"))
    code = str(payload.get("code") or "")
    if kind not in (KIND_LOGIN_EXPIRED, KIND_LIMIT_REACHED, KIND_PLATFORM_REFUSED):
        return None
    if not all(safe_code(part) for part in code.split("/")):
        return None
    at = payload.get("at")
    return SeatFailure(kind, code, float(at) if isinstance(at, int | float) else 0.0)


def record_failure(state: LocalState, session_key: str, failure: SeatFailure) -> None:
    payload = {"kind": failure.kind, "code": failure.code, "at": failure.at}
    write_private_json(state.session_dir(session_key) / SESSION_FAILURE_FILE, {**payload, "shown": False})
    if failure.kind != KIND_PLATFORM_REFUSED:
        write_private_json(state.root / PROBLEM_FILE, payload)


def session_failure(state: LocalState, session_key: str) -> SeatFailure | None:
    return _failure_from(read_json(state.session_dir(session_key) / SESSION_FAILURE_FILE))


def take_unshown_failure(state: LocalState, session_key: str) -> SeatFailure | None:
    """The session's failure once: the second call returns ``None``."""
    path = state.session_dir(session_key) / SESSION_FAILURE_FILE
    payload = read_json(path)
    failure = _failure_from(payload)
    if failure is None or payload.get("shown"):
        return None
    write_private_json(path, {**payload, "shown": True})
    return failure


def clear_problem(state: LocalState) -> None:
    with contextlib.suppress(FileNotFoundError):
        (state.root / PROBLEM_FILE).unlink()


def clear_after_success(state: LocalState, session_key: str) -> None:
    """A seat turn completed: the subscription works again."""
    with contextlib.suppress(FileNotFoundError):
        (state.session_dir(session_key) / SESSION_FAILURE_FILE).unlink()
    clear_problem(state)


def stored_problem(state: LocalState, *, now: float | None = None) -> SeatFailure | None:
    """The last subscription problem; a limit counts for ``LIMIT_WINDOW_SECONDS`` only."""
    failure = _failure_from(read_json(state.root / PROBLEM_FILE))
    if failure is None:
        return None
    current = time.time() if now is None else now
    if failure.kind == KIND_LIMIT_REACHED and current - failure.at >= LIMIT_WINDOW_SECONDS:
        return None
    return failure


def seat_refusal(policy: dict[str, Any]) -> str:
    """``""`` when the client policy allows the seat profile, else its fixed reason."""
    seat = policy.get("seat") if isinstance(policy.get("seat"), dict) else {}
    if safe_code(seat.get("seat_mode")) == "allowed":
        return ""
    return safe_code(seat.get("reason")) or "seat_mode_forbidden"


def seat_state(state: LocalState, *, policy_ok: bool, seat_refusal: str, logged_in: bool,
               now: float | None = None) -> SeatState:
    if not policy_ok:
        return SeatState(STATE_UNKNOWN, "unknown (client policy unavailable)")
    if seat_refusal:
        return SeatState(STATE_FORBIDDEN, f"not allowed by the Workspace ({seat_refusal})", seat_refusal)
    problem = stored_problem(state, now=now)
    if problem is not None and problem.kind == KIND_LOGIN_EXPIRED:
        return SeatState(STATE_LOGIN_EXPIRED, f"login expired (rejected at {_clock(problem.at)})")
    if not logged_in:
        # Presence only: a Claude login kept elsewhere (the macOS Keychain) is not visible here (outsider walk
        # "not logged in" while the seat worked), so the label says what is known.
        return SeatState(STATE_NOT_LOGGED_IN, NO_LOGIN_RECORDED)
    if problem is not None:
        return SeatState(STATE_LIMIT_REACHED, f"limit reached (at {_clock(problem.at)}; counts for 5h)")
    return SeatState(STATE_READY, "ready")


def finish_seat_session(state: LocalState, session_key: str, exit_code: int, out: TextIO) -> bool:
    """After a seat session: say what failed and how to fix it; ``True`` when the seat login proved itself."""
    failure = session_failure(state, session_key)
    if failure is not None:
        out.write(f"octryx-claude: {failure_message(failure)}\n")
        out.flush()
        return False
    return exit_code == 0


__all__ = [
    "SEAT_LOGIN_COMMAND",
    "SeatFailure",
    "SeatState",
    "classify_failure",
    "clear_after_success",
    "codex_limit_code",
    "clear_problem",
    "failure_message",
    "finish_seat_session",
    "record_failure",
    "seat_refusal",
    "seat_state",
    "session_failure",
    "stored_problem",
    "take_unshown_failure",
    "turn_limit_code",
]
