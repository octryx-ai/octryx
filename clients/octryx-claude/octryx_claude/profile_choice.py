"""``--profile auto``: seat when it can work, governed otherwise; decided once at launch for the whole session."""

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
    if (state.claude_config_dir_for(PROFILE_SEAT) / CLAUDE_CREDENTIAL_FILE).exists():
        return True
    from .codex_seat import seat_home  # noqa: PLC0415

    if (seat_home(state.root) / "auth.json").exists():
        return True  # a device with only the person's ChatGPT login offers the seat profile for Codex jobs
    return (state.root / SEAT_SESSION_MARKER).exists()


def mark_seat_session_ok(state: LocalState) -> None:
    state.ensure()
    (state.root / SEAT_SESSION_MARKER).touch(mode=0o600)


_AUTO_GOVERNED_REASONS = {
    seat_status.STATE_UNKNOWN: "seat state unknown",
    seat_status.STATE_LOGIN_EXPIRED: "seat login expired",
    seat_status.STATE_NOT_LOGGED_IN: "no seat login recorded",
}


def choose_profile(requested: str, *, seat: SeatState) -> ProfileChoice:
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
