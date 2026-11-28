"""Seat-profile hook steps ("if the subscription fails, I must see it right away")."""

from __future__ import annotations

import json
import os
import sys

from . import seat_status
from .launch_process import PROFILE_SEAT
from .platform import ENV_PROFILE, SessionContext
from .state import LocalState

MAX_HOOK_INPUT_BYTES = 1024 * 1024


def _seat_context() -> SessionContext | None:
    if os.environ.get(ENV_PROFILE) != PROFILE_SEAT:
        return None
    return SessionContext.from_env()


def run_stop_failure(state: LocalState) -> int:
    try:
        context = _seat_context()
        if context is None:
            return 0
        hook_input = json.loads(sys.stdin.read(MAX_HOOK_INPUT_BYTES) or "{}")
        if not isinstance(hook_input, dict) or hook_input.get("hook_event_name") != "StopFailure":
            return 0
        failure = seat_status.classify_failure(hook_input)
        if failure is not None:
            seat_status.record_failure(state, context.session_key, failure)
    except Exception:  # noqa: BLE001 - fire and forget; Claude Code ignores this hook anyway
        pass
    return 0


def seat_notice(state: LocalState) -> str:
    try:
        context = _seat_context()
        failure = seat_status.take_unshown_failure(state, context.session_key) if context else None
    except Exception:  # noqa: BLE001 - a notice never disturbs the prompt
        return ""
    return f"octryx-claude: {seat_status.failure_message(failure)}" if failure else ""


def seat_turn_done(state: LocalState) -> None:
    try:
        context = _seat_context()
        if context is not None:
            seat_status.clear_after_success(state, context.session_key)
    except Exception:  # noqa: BLE001 - best effort
        pass


__all__ = ["run_stop_failure", "seat_notice", "seat_turn_done"]
