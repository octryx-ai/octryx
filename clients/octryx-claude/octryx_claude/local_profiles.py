"""Claude Code profiles outside octryx on this machine (P6b).

Owner runs several Claude Code profiles side by side: Team (``~/.claude``, started with ``claude-work``), Private
(``~/.claude-private``, the ``claude`` shell function sets ``CLAUDE_CONFIG_DIR``), and octryx's own. The person's
private Workspace shows the sessions of the profiles they **connect** here, and they can take one over from the
phone (the device job runs ``resume`` in that profile and folder).

- :func:`discover`: ``~/.claude``, every ``~/.claude-*`` with a ``projects`` folder, and every ``CLAUDE_CONFIG_DIR``
  a shell start file sets; never octryx's own config dirs.
- :func:`connect` / :func:`disconnect`: only what the person connected is ever read or reported (concept N1:
  connect after confirmation). Stored in ``local-profiles.json`` in the state dir.
- :func:`report`: the connected profiles and their recent sessions (title, folder, last answer, last change),
  titles and answers redacted like the session digest (``mobile_summary``) before anything leaves the machine.
- :func:`session_folder`: the folder a session ran in, read from its own transcript; the device job runs a
  take-over only there (``device_jobs``).
- :func:`profile_env`: the environment for that profile. ``~/.claude`` is Claude Code's default and must be reached
  by *unsetting* ``CLAUDE_CONFIG_DIR`` (pointing at it would be another profile to Claude Code).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import LocalState, write_private_json

FILE_NAME = "local-profiles.json"
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,7}$")
SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SHELL_FILES = (".zshrc", ".zprofile", ".zshenv", ".bashrc", ".bash_profile", ".profile")
CONFIG_ASSIGNMENT = re.compile(r"CLAUDE_CONFIG_DIR=[\"']?([^\"'\s;)]+)")
MAX_SESSIONS_PER_PROFILE = 25
MAX_SESSIONS = 60
RECENT_DAYS = 14
HEAD_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class LocalProfile:
    name: str
    config_dir: Path
    # Remote runs are a separate, explicit opt-in (``profiles connect --allow-takeover``).
    allow_takeover: bool = False

    @property
    def is_default(self) -> bool:
        return self.config_dir == default_dir()


def default_dir() -> Path:
    return (Path.home() / ".claude").resolve()


def _expand(raw: str) -> Path:
    return Path(os.path.expandvars(raw.replace("$HOME", str(Path.home())).replace("${HOME}", str(Path.home())))
                ).expanduser()


def _own_dirs(state: LocalState) -> set[Path]:
    own = {state.root.resolve()}
    for profile in ("governed", "seat"):
        try:
            own.add(Path(state.claude_config_dir_for(profile)).resolve())
        except Exception:  # noqa: BLE001 - an unconfigured octryx state has no own profiles yet
            continue
    return own


def _inside(path: Path, roots: set[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def suggested_name(config_dir: Path) -> str:
    if config_dir == default_dir():
        return "default"
    stem = config_dir.name.removeprefix(".claude").strip("-_.").lower() or "profile"
    return re.sub(r"[^a-z0-9_-]", "", stem)[:8] or "profile"


def discover(state: LocalState, *, home: Path | None = None) -> list[Path]:
    """Claude Code config dirs on this machine, octryx's own excluded; each only once."""
    home = home or Path.home()
    found: list[Path] = []
    candidates = [home / ".claude", *sorted(home.glob(".claude-*"))]
    for name in SHELL_FILES:
        try:
            text = (home / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        candidates += [_expand(match) for match in CONFIG_ASSIGNMENT.findall(text)]
    own = _own_dirs(state)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in found or _inside(resolved, own) or not (resolved / "projects").is_dir():
            continue
        found.append(resolved)
    return found


def connected(state: LocalState) -> list[LocalProfile]:
    try:
        raw = json.loads((state.root / FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("profiles") if isinstance(raw, dict) else None
    profiles = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and NAME.match(item["name"]) \
                and isinstance(item.get("config_dir"), str):
            profiles.append(LocalProfile(item["name"], Path(item["config_dir"]), item.get("allow_takeover") is True))
    return profiles


def _save(state: LocalState, profiles: list[LocalProfile]) -> None:
    write_private_json(state.root / FILE_NAME, {"profiles": [
        {"name": profile.name, "config_dir": str(profile.config_dir), "allow_takeover": profile.allow_takeover}
        for profile in profiles]})


class ProfileError(ValueError):
    pass


def connect(state: LocalState, config_dir: str | Path, *, name: str = "", allow_takeover: bool = False) -> LocalProfile:
    path = _expand(str(config_dir)).resolve()
    if _inside(path, _own_dirs(state)):
        raise ProfileError("octryx's own profiles are already part of Octryx")
    if not (path / "projects").is_dir():
        raise ProfileError(f"{path} is not a Claude Code profile (no projects folder)")
    name = (name or suggested_name(path)).lower()
    if not NAME.match(name):
        raise ProfileError("a profile name is 1-8 characters: a-z, 0-9, - and _")
    profiles = [profile for profile in connected(state) if profile.config_dir != path]
    if any(profile.name == name for profile in profiles):
        raise ProfileError(f"the name {name!r} is already used by another profile")
    profile = LocalProfile(name, path, allow_takeover)
    _save(state, [*profiles, profile])
    return profile


def disconnect(state: LocalState, name: str) -> bool:
    profiles = connected(state)
    kept = [profile for profile in profiles if profile.name != name]
    _save(state, kept)
    return len(kept) != len(profiles)


def find(state: LocalState, name: str) -> LocalProfile | None:
    return next((profile for profile in connected(state) if profile.name == name), None)


def profile_env(profile: LocalProfile, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK"):
        env.pop(key, None)  # the profile's own login pays, never an octryx or platform credential
    if profile.is_default:
        env.pop("CLAUDE_CONFIG_DIR", None)
    else:
        env["CLAUDE_CONFIG_DIR"] = str(profile.config_dir)
    return env


def _transcripts(profile: LocalProfile) -> list[Path]:
    since = time.time() - RECENT_DAYS * 86400
    files = []
    for path in (profile.config_dir / "projects").glob("*/*.jsonl"):
        if not SESSION_ID.match(path.stem):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= since:
            files.append((mtime, path))
    return [path for _mtime, path in sorted(files, reverse=True)[:MAX_SESSIONS_PER_PROFILE]]


def _cwd(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            head = handle.read(HEAD_BYTES)
    except OSError:
        return ""
    for raw in head.splitlines():
        try:
            entry = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        cwd = entry.get("cwd") if isinstance(entry, dict) else None
        if isinstance(cwd, str) and cwd.startswith("/"):
            return cwd
    return ""


def session_folder(profile: LocalProfile, session_id: str) -> str:
    """The folder ``session_id`` ran in, from its own transcript in this profile; ``""`` when it is not there."""
    if not SESSION_ID.match(session_id or ""):
        return ""
    for path in (profile.config_dir / "projects").glob(f"*/{session_id}.jsonl"):
        return _cwd(path)
    return ""


_SUMMARIES: dict[tuple[str, float], dict[str, Any]] = {}


def _entry(profile: LocalProfile, path: Path) -> dict[str, Any] | None:
    from . import mobile_summary  # noqa: PLC0415 - the redaction loads the digest's helpers lazily

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    cached = _SUMMARIES.get(key)
    if cached is None:
        cwd = _cwd(path)
        if not cwd:
            return None
        try:
            summary = mobile_summary.read_summary(path)
        except Exception:  # noqa: BLE001 - an unreadable transcript is listed without its texts
            summary = {}
        cached = {"cwd": cwd, "title": summary.get("title", ""), "last_text": summary.get("last_text", "")[-2000:]}
        _SUMMARIES[key] = cached
    return {"profile": profile.name, "session_id": path.stem, "cwd": cached["cwd"], "title": cached["title"],
            "last_text": cached["last_text"],
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime))}


def report(state: LocalState) -> dict[str, Any]:
    """``{profiles, sessions}`` for the platform (channel message ``local_sessions``); never raises."""
    profiles = connected(state)
    sessions: list[dict[str, Any]] = []
    for profile in profiles:
        try:
            for path in _transcripts(profile):
                if (entry := _entry(profile, path)) is not None:
                    sessions.append(entry)
        except Exception:  # noqa: BLE001 - one unreadable profile never hides the others
            continue
    sessions.sort(key=lambda item: item["updated_at"], reverse=True)
    if len(_SUMMARIES) > 500:
        _SUMMARIES.clear()
    return {"profiles": [profile.name for profile in profiles],
            "takeover_profiles": [profile.name for profile in profiles if profile.allow_takeover],
            "sessions": sessions[:MAX_SESSIONS]}


__all__ = ["LocalProfile", "ProfileError", "connect", "connected", "default_dir", "disconnect", "discover", "find",
           "profile_env", "report", "session_folder", "suggested_name"]
