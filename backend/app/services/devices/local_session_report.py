"""What a device may report about its Claude Code sessions outside octryx: every field bounded and checked
(``devices.local_sessions``)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

MAX_SESSIONS = 60
MAX_PROFILES = 8
MAX_TITLE = 200
MAX_LAST_TEXT = 2000
MAX_CWD = 500
PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,7}$")
SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\x00", "").strip()
    return cleaned[:limit] or None


def _cwd(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("/") or "\x00" in value or len(value) > MAX_CWD:
        return None
    return value


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def normalize_report(body: Any) -> tuple[list[str], list[dict[str, Any]]]:
    """``(profiles, sessions)`` from a device report; anything malformed is dropped, never stored."""
    raw_profiles = body.get("profiles") if isinstance(body, dict) else None
    profiles = []
    for name in raw_profiles if isinstance(raw_profiles, list) else []:
        if isinstance(name, str) and PROFILE_NAME.match(name) and name not in profiles:
            profiles.append(name)
    profiles = profiles[:MAX_PROFILES]
    raw_takeover = body.get("takeover_profiles") if isinstance(body, dict) else None
    takeover = {name for name in raw_takeover if name in profiles} if isinstance(raw_takeover, list) else set()
    raw_sessions = body.get("sessions") if isinstance(body, dict) else None
    sessions, seen = [], set()
    for item in raw_sessions if isinstance(raw_sessions, list) else []:
        if not isinstance(item, dict) or len(sessions) >= MAX_SESSIONS:
            continue
        profile, session_id, cwd = item.get("profile"), item.get("session_id"), _cwd(item.get("cwd"))
        if profile not in profiles or not isinstance(session_id, str) or not SESSION_ID.match(session_id) or not cwd:
            continue
        if (profile, session_id) in seen:
            continue
        seen.add((profile, session_id))
        sessions.append({"profile": profile, "claude_session_id": session_id, "cwd": cwd,
                         "title": _text(item.get("title"), MAX_TITLE),
                         "last_text": _text(item.get("last_text"), MAX_LAST_TEXT),
                         "updated_at": _when(item.get("updated_at")),
                         "takeover_allowed": profile in takeover})
    return profiles, sessions

