"""Per-session rules of the launcher: grant scopes and once-per-session notices."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from .oauth import SCOPES
from .state import LocalState, read_json, write_private_json

BOARD_SCOPE = "work:manage"
# ``analyze``: knowledge_search/knowledge_read need knowledge:read; work_item_context and
# work_item_analysis_submit run in the secure-work family under work:manage.
ANALYZE_SCOPES = ("knowledge:read", BOARD_SCOPE)
ENV_SESSION_MODE = "OCTRYX_SESSION_MODE"
MODE_HEADLESS = "headless"
MODE_INTERACTIVE = "interactive"
_HEADLESS_FLAGS = frozenset({"-p", "--print"})
VERIFICATION_NOTICE_FILE = "verification_notice.json"
LOGIN_COMMAND = "octryx-claude login"


def requested_scopes() -> tuple[str, ...]:
    return tuple(SCOPES.split())


def granted_scopes(state: LocalState) -> frozenset[str] | None:
    scopes = state.credentials().get("scopes")
    if not isinstance(scopes, list):
        return None
    return frozenset(scope for scope in scopes if isinstance(scope, str))


def missing_scopes(state: LocalState, required: Sequence[str] | None = None) -> list[str]:
    wanted = requested_scopes() if required is None else tuple(required)
    if not str(state.credentials().get("refresh_token") or ""):
        return []  # not logged in: the login check refuses, never a scope claim
    granted = granted_scopes(state)
    if granted is None:  # no grant record: nothing is granted until the next login records it
        return list(wanted)
    return [scope for scope in wanted if scope not in granted]


def can_read_board(state: LocalState) -> bool:
    return BOARD_SCOPE in (granted_scopes(state) or frozenset())


def lacks_scopes_message(missing: Sequence[str]) -> str:
    return f"your login lacks {', '.join(missing)}; run {LOGIN_COMMAND}"


def scope_notice(state: LocalState) -> str:
    missing = missing_scopes(state)
    if not missing:
        return ""
    notice = lacks_scopes_message(missing)
    if BOARD_SCOPE in missing:
        notice += (" (until then the agent board, work-item claims, offers, the agent's handoff tools and "
                   "`octryx-claude analyze` are unavailable; `octryx-claude handoff` and /handoff still work)")
    return notice


def analyze_scope_refusal(state: LocalState) -> str:
    missing = missing_scopes(state, ANALYZE_SCOPES)
    return lacks_scopes_message(missing) if missing else ""


def headless_session(claude_args: Sequence[str]) -> bool:
    return any(arg in _HEADLESS_FLAGS or arg.startswith("--print=") for arg in claude_args)


def is_headless(environ: Mapping[str, str] | None = None) -> bool:
    return (os.environ if environ is None else environ).get(ENV_SESSION_MODE) == MODE_HEADLESS


def record_verification_notice(state: LocalState, session_key: str, verification_state: str) -> None:
    write_private_json(state.session_dir(session_key) / VERIFICATION_NOTICE_FILE, {"state": verification_state})


def verification_notice_once(state: LocalState, session_key: str, output: dict[str, Any] | None,
                             verification_state: str) -> dict[str, Any] | None:
    if verification_state != "needs_configuration" or not output or "systemMessage" not in output:
        return output
    path = state.session_dir(session_key) / VERIFICATION_NOTICE_FILE
    if read_json(path).get("state") == verification_state:
        rest = {key: value for key, value in output.items() if key != "systemMessage"}
        return rest or None
    write_private_json(path, {"state": verification_state})
    return output


__all__ = [
    "ANALYZE_SCOPES",
    "BOARD_SCOPE",
    "ENV_SESSION_MODE",
    "MODE_HEADLESS",
    "MODE_INTERACTIVE",
    "analyze_scope_refusal",
    "can_read_board",
    "granted_scopes",
    "headless_session",
    "is_headless",
    "lacks_scopes_message",
    "missing_scopes",
    "record_verification_notice",
    "requested_scopes",
    "scope_notice",
    "verification_notice_once",
]
