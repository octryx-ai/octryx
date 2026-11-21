"""Per-session rules of the launcher found in the owner's live seat session (seat findings SL-1, SL-2, SL-5).

- **SL-1, grant scopes:** the login stores the scopes the platform granted (``credentials["scopes"]``, from the
  token response's ``scope`` field, which the platform always sends on code exchange and refresh; a login whose
  answer lacks ``model:invoke`` is refused, so every login since the record exists has one). Every start compares
  the scopes the launcher requests now (``oauth.SCOPES``) with the record and prints one line per start naming the
  missing ones and ``octryx-claude login`` as the fix; ``analyze`` refuses up front when a scope it needs is
  missing instead of failing at submit with HTTP 403. The unread reminder is only given when the grant can read
  the board.
- **No grant record:** a stored login without ``credentials["scopes"]`` is treated as lacking every requested
  scope, so the start notice and ``analyze`` ask for ``octryx-claude login``; nothing is inferred from its age.
- **SL-2, the verification notice:** "verification is not configured" is said once per session (the launcher
  already says it at start); later stops stay silent while the state is unchanged.
- **SL-5, headless runs:** the launcher marks a ``-p``/``--print`` session as headless (``OCTRYX_SESSION_MODE``);
  there the board reminder and the handoff nudges never block a stop, they are informational output only.
"""

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
    """The scopes the launcher asks for at login today."""
    return tuple(SCOPES.split())


def granted_scopes(state: LocalState) -> frozenset[str] | None:
    """The scopes of the stored login, or ``None`` when it has no grant record."""
    scopes = state.credentials().get("scopes")
    if not isinstance(scopes, list):
        return None
    return frozenset(scope for scope in scopes if isinstance(scope, str))


def missing_scopes(state: LocalState, required: Sequence[str] | None = None) -> list[str]:
    """The ``required`` scopes (default: all requested ones) the stored login is known to lack."""
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
    """The start notice when the login lacks a scope the launcher requests now; ``""`` when nothing is missing."""
    missing = missing_scopes(state)
    if not missing:
        return ""
    notice = lacks_scopes_message(missing)
    if BOARD_SCOPE in missing:
        notice += (" (until then the agent board, work-item claims, offers, the agent's handoff tools and "
                   "`octryx-claude analyze` are unavailable; `octryx-claude handoff` and /handoff still work)")
    return notice


def analyze_scope_refusal(state: LocalState) -> str:
    """``""`` when the login carries every scope ``analyze`` needs, else the same lacks-scope message."""
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
    """Drop a repeated ``needs_configuration`` notice: it is shown once per session and state."""
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
