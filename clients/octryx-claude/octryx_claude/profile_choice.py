"""``--profile auto`` (the default, owner): seat when it can work, governed otherwise.

Decided **once at launch**, before the session registers; the chosen profile then stays for the whole session (it is
registered with the platform and fixes the model route), so a session never switches profile.

``auto`` is ``seat`` only when both hold:

1. the Workspace's client policy allows seat right now (``seat.seat_mode`` is the platform's effective decision,
   classification included);
2. the seat profile is logged in to the user's own Claude subscription. Detected **without reading any credential**:
   Claude Code's own credential file exists in ``claude-config-seat/`` (presence only; on macOS Claude Code keeps the
   login in the Keychain instead), or the launcher's marker that a seat session ended normally before.

A seat login that was rejected, or a subscription limit reached in the last five hours (``seat_status``), also
means ``governed``. Explicit ``--profile seat|governed`` behaves. The status block says what was chosen
and why.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import seat_status
from .launch_process import PROFILE_GOVERNED, PROFILE_SEAT
from .seat_status import SeatState
from .state import LocalState

PROFILE_AUTO = "auto"
CLAUDE_CREDENTIAL_FILE = ".credentials.json"
SEAT_SESSION_MARKER = ".seat-session-ok"


@dataclass(frozen=True)
class ProfileChoice:
    profile: str
    reason: str


def seat_logged_in(state: LocalState) -> bool:
    """Presence checks only: Claude Code's credential file, the Codex seat's login file (``codex_seat``, never
    read), or the launcher's marker of an earlier seat session."""
    if (state.claude_config_dir_for(PROFILE_SEAT) / CLAUDE_CREDENTIAL_FILE).exists():
        return True
    from .codex_seat import seat_home  # noqa: PLC0415

    if (seat_home(state.root) / "auth.json").exists():
        return True  # a device with only the person's ChatGPT login offers the seat profile for Codex jobs
    return (state.root / SEAT_SESSION_MARKER).exists()


def mark_seat_session_ok(state: LocalState) -> None:
    """A seat session ended normally: the seat login works (the file holds nothing)."""
    state.ensure()
    (state.root / SEAT_SESSION_MARKER).touch(mode=0o600)


_AUTO_GOVERNED_REASONS = {
    seat_status.STATE_UNKNOWN: "seat state unknown",
    seat_status.STATE_LOGIN_EXPIRED: "seat login expired",
    seat_status.STATE_NOT_LOGGED_IN: "no seat login recorded",
}


def choose_profile(requested: str, *, seat: SeatState) -> ProfileChoice:
    """``requested`` (seat, governed or auto) → the session's profile and why."""
    if requested != PROFILE_AUTO:
        return ProfileChoice(requested, f"--profile {requested}")
    if seat.code == seat_status.STATE_READY:
        return ProfileChoice(PROFILE_SEAT, "auto: Workspace allows seat and the seat login is present")
    if seat.code == seat_status.STATE_FORBIDDEN:
        return ProfileChoice(PROFILE_GOVERNED, f"auto: Workspace forbids seat: {seat.reason}")
    if seat.code == seat_status.STATE_LIMIT_REACHED:
        return ProfileChoice(PROFILE_GOVERNED, f"auto: seat {seat.label}")
    return ProfileChoice(PROFILE_GOVERNED, f"auto: {_AUTO_GOVERNED_REASONS.get(seat.code, seat.code)}")


__all__ = ["PROFILE_AUTO", "ProfileChoice", "choose_profile", "mark_seat_session_ok", "seat_logged_in"]
