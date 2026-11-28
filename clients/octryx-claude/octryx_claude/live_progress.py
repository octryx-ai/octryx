"""What a running Claude Code session is doing, for the person's phone, read from its own transcript."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .device_sdk_events import input_preview
from .live_sessions import RELAY_NAME, _profile_dirs
from .session_lessons import redact
from .state import LocalState

MAX_TEXT = 600
MAX_PROMPT = 300
MAX_LINE = 160
MAX_EVENTS = 50
FIRST_LOOK_BYTES = 96 * 1024
MAX_READ_BYTES = 1024 * 1024
FIRST_LOOK_EVENTS = 30
SILENT_RESULTS = frozenset({"Read", "Grep", "Glob", "NotebookRead", "WebFetch", "WebSearch", "LS"})
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
PRINTS_FILE = re.compile(r"(^|[;&|(\n]|\$\()\s*(sudo\s+)?(cat|head|tail|less|more|sed\s+-n|awk|strings|xxd|od|"
                         r"hexdump|bat|base64|nl|jq|yq|grep|rg|security|pbpaste|env|printenv|openssl)\b")

# Commands whose output is a secret's raw value: the secret filter only knows shapes, not raw values,
# so their output never leaves the Mac, wherever they stand in a command line.
SECRET_COMMANDS = re.compile(
    r"\b(aws\s+(secretsmanager|ssm|kms|sts|iam\s+create-access-key|ecr\s+get-login|configure\s+(get|export))"
    r"|kubectl\b[^;&|\n]*\b(secrets?|serviceaccount|token|config\s+view)\b"
    r"|oc\b[^;&|\n]*\bsecrets?\b"
    r"|helm\s+get\s+values"
    r"|vault\s+(kv|read|write|token|login|print|secrets)"
    r"|gcloud\b[^;&|\n]*\b(secrets|auth\s+(print-access-token|print-identity-token|application-default))"
    r"|az\s+(keyvault|account\s+get-access-token|ad\s+sp\s+credential)"
    r"|op\s+(read|item|inject|signin|document)"
    r"|gh\s+auth\s+(token|status)"
    r"|git\s+credential|git\s+config\b[^;&|\n]*\b(credential|token|password)"
    r"|docker\s+(login|secret)|podman\s+login"
    r"|doppler\s+(secrets|run)|pass\s+(show|ls|find|grep)|gopass|bw\s+(get|list|unlock)|lpass\s+show"
    r"|sops\s+(-d|--decrypt|exec)|age\s+(-d|--decrypt)|gpg\s+(-d|--decrypt)"
    r"|keychain|security\s+find-|npm\s+token|cat\s+[^;&|\n]*\.(npmrc|netrc|pgpass))",
    re.IGNORECASE,
)


def _quiet(name: str, tool_input: dict[str, Any]) -> bool:
    if name in SILENT_RESULTS:
        return True
    command = str(tool_input.get("command") or "")
    return name == "Bash" and bool(PRINTS_FILE.search(command) or SECRET_COMMANDS.search(command))


def enabled(state: LocalState) -> bool:
    return state.config().get("live_progress") is not False


def transcript_path(state: LocalState, session: dict[str, Any], *, home: Path | None = None) -> Path | None:
    session_id = str(session.get("session_id") or "")
    if not _SESSION_ID.match(session_id):
        return None
    for label, config_dir in _profile_dirs(state, home or Path.home()):
        if label != session.get("profile"):
            continue
        projects = (config_dir / "projects").resolve()
        for candidate in projects.glob(f"*/{session_id}.jsonl"):
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.parent.parent == projects and resolved.is_file() and not candidate.is_symlink():
                return resolved
    return None


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split()) if limit <= MAX_LINE else str(text).strip()
    return redact(text[:limit] + ("…" if len(text) > limit else ""))


def _first_line(content: Any) -> str:
    if isinstance(content, list):
        content = "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    for line in str(content or "").splitlines():
        if line.strip():
            return _clip(line, MAX_LINE)
    return ""


def events_from(lines: list[str], tools: dict[str, bool]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain"):
            continue
        at = str(entry.get("timestamp") or "")[:40]
        boundary = entry.get("type") == "system" and entry.get("subtype") == "compact_boundary"
        if entry.get("isCompactSummary") or boundary:
            events.append({"kind": "compact", "at": at})
            continue
        origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
        if entry.get("type") == "user" and origin.get("kind") == "peer" and isinstance(origin.get("body"), str):
            sender = str(origin.get("name") or "another session")[:60]
            if sender != RELAY_NAME:  # the phone's own messages are already in the chat
                events.append({"kind": "prompt", "from": sender, "text": _clip(origin["body"], MAX_PROMPT), "at": at})
            continue
        if entry.get("isMeta"):
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        content = message.get("content")
        if entry.get("type") == "user":
            events.extend(_user_events(content, tools, at))
        elif entry.get("type") == "assistant":
            events.extend(_assistant_events(content, tools, at))
    return events


def _user_events(content: Any, tools: dict[str, bool], at: str) -> list[dict[str, Any]]:
    if isinstance(content, str):
        if content.strip() and not content.lstrip().startswith(("<", "Caveat:")):
            return [{"kind": "prompt", "from": "", "text": _clip(content, MAX_PROMPT), "at": at}]
        return []
    events: list[dict[str, Any]] = []
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "tool_result":
            tool_id = str(part.get("tool_use_id") or "")[:80]
            quiet = tools.pop(tool_id, True)  # an unknown call says nothing
            event = {"kind": "result", "id": tool_id, "ok": not part.get("is_error"), "at": at}
            if not quiet:
                event["line"] = _first_line(part.get("content"))
            events.append(event)
        elif part.get("type") == "text" and str(part.get("text") or "").strip():
            text = str(part["text"])
            if not text.lstrip().startswith(("<", "Caveat:")):
                events.append({"kind": "prompt", "from": "", "text": _clip(text, MAX_PROMPT), "at": at})
    return events


def _assistant_events(content: Any, tools: dict[str, bool], at: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and str(part.get("text") or "").strip():
            events.append({"kind": "text", "text": _clip(part["text"], MAX_TEXT), "at": at})
        elif part.get("type") == "tool_use":
            name = str(part.get("name") or "")[:60]
            tool_id = str(part.get("id") or "")[:80]
            tool_input = part.get("input") if isinstance(part.get("input"), dict) else {}
            if len(tools) > 200:
                tools.pop(next(iter(tools)))
            tools[tool_id] = _quiet(name, tool_input)
            events.append({"kind": "tool", "id": tool_id, "tool": name,
                           "input": _clip(input_preview(name, tool_input), MAX_LINE), "at": at})
    return events


class ProgressTail:
    def __init__(self, state: LocalState, *, home: Path | None = None) -> None:
        self.state = state
        self.home = home
        self._seen: dict[str, dict[str, Any]] = {}  # peer -> {"path", "offset", "tools"}

    def collect(self, sessions: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
        listed = {str(item.get("peer") or "") for item in sessions}
        for gone in set(self._seen) - listed:
            self._seen.pop(gone, None)
        out: list[tuple[str, list[dict[str, Any]]]] = []
        for session in sessions:
            peer = str(session.get("peer") or "")
            try:
                events = self._read(peer, session)
            except OSError:
                continue
            if events:
                out.append((peer, events))
        return out

    def _read(self, peer: str, session: dict[str, Any]) -> list[dict[str, Any]]:
        path = transcript_path(self.state, session, home=self.home)
        if path is None:
            return []
        seen = self._seen.get(peer)
        size = os.path.getsize(path)
        first = seen is None or seen["path"] != path or size < seen["offset"]  # new, another transcript, or rewritten
        start = max(0, size - FIRST_LOOK_BYTES) if first else seen["offset"]
        tools: dict[str, bool] = {} if first else seen["tools"]
        with path.open("rb") as handle:
            handle.seek(start)
            data = handle.read(min(size - start, MAX_READ_BYTES))
        end = data.rfind(b"\n") + 1  # a half-written last line waits for the next round
        chunk = data[:end].decode("utf-8", errors="replace").splitlines()
        if first and start > 0 and chunk:
            chunk = chunk[1:]  # the first line of a tail may be cut
        self._seen[peer] = {"path": path, "offset": start + end, "tools": tools}
        events = events_from(chunk, tools)
        return events[-FIRST_LOOK_EVENTS:] if first else events[-MAX_EVENTS:]


__all__ = ["ProgressTail", "enabled", "events_from", "transcript_path"]
