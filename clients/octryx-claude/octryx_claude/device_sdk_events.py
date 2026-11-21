"""What a device turn shows in the chat: tool input previews, code-change diffs (never of a secret file), clipped
results, context fill and the job events mapped from the SDK's messages (``device_sdk``)."""

from __future__ import annotations

import json
from typing import Any

MAX_PREVIEW_CHARS = 2000
MAX_RESULT_CHARS = 4000


def input_preview(tool: str, tool_input: dict[str, Any]) -> str:
    if tool == "Bash" and isinstance(tool_input.get("command"), str):
        text = tool_input["command"]
    elif isinstance(tool_input.get("file_path"), str):
        text = tool_input["file_path"]
    else:
        text = json.dumps(tool_input, ensure_ascii=False, default=str)
    return text[:MAX_PREVIEW_CHARS]


MAX_DIFF_CHARS = 8000
_SECRET_NAMES = ("credentials", "secret", "token", "password", "passwd", ".netrc", ".npmrc", ".pypirc", "id_rsa",
                 "id_ed25519", "id_ecdsa", "id_dsa")
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".gpg", ".asc", "history",
                    ".keychain", ".keychain-db")
# Browser and system stores, shell histories and the config folders of CLI logins.
_SECRET_PARTS = ("keychain", "cookies", "login data", "web data", "kubeconfig", "hosts.yml", "auth.json")
_SECRET_FOLDERS = ("/.ssh/", "/.aws/", "/.gnupg/", "/.kube/", "/.docker/", "/.config/gh/", "/.config/gcloud/",
                   "/.azure/", "/.octryx/", "/library/keychains/", "/library/cookies/")


def secret_path(path: str) -> bool:
    """A file whose content is likely a secret: no diff or file of it leaves the Mac."""
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    return (name == ".env" or name.startswith(".env.") or name.endswith(_SECRET_SUFFIXES)
            or any(part in name for part in _SECRET_NAMES + _SECRET_PARTS)
            or any(folder in normalized for folder in _SECRET_FOLDERS) or "/.claude" in normalized)


def change_diff(tool: str, tool_input: dict[str, Any]) -> str:
    """A unified diff of an Edit/MultiEdit, or the new file of a Write, for the app's code-change view; capped."""
    import difflib  # noqa: PLC0415

    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "file")
    if secret_path(path):
        return ""  # review: secrets never reach the platform in a diff (.env, keys, credentials)
    if tool == "Edit":
        pairs = [(tool_input.get("old_string"), tool_input.get("new_string"))]
    elif tool == "MultiEdit" and isinstance(tool_input.get("edits"), list):
        pairs = [(edit.get("old_string"), edit.get("new_string")) for edit in tool_input["edits"]
                 if isinstance(edit, dict)]
    elif tool == "Write" and isinstance(tool_input.get("content"), str):
        lines = tool_input["content"].splitlines()
        text = f"+++ {path} (new content)\n" + "\n".join(f"+{line}" for line in lines)
        return text[:MAX_DIFF_CHARS]
    else:
        return ""
    chunks = []
    for old, new in pairs:
        if not isinstance(old, str) or not isinstance(new, str):
            continue
        chunks.extend(difflib.unified_diff(old.splitlines(), new.splitlines(), fromfile=path, tofile=path,
                                           lineterm="", n=2))
    return "\n".join(chunks)[:MAX_DIFF_CHARS]


def _clip(value: Any, limit: int = MAX_RESULT_CHARS) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(value) <= limit else value[:limit] + "…"

def context_tokens(message: Any) -> int | None:
    """How full the context is after one main-thread API call: its input (with cache) plus its output tokens."""
    if type(message).__name__ != "AssistantMessage" or getattr(message, "parent_tool_use_id", None):
        return None
    usage = getattr(message, "usage", None)
    if not isinstance(usage, dict):
        return None
    total = sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_read_input_tokens",
                                                       "cache_creation_input_tokens", "output_tokens"))
    return total or None


def context_window(model_usage: Any) -> int:
    """The largest context window the turn's models report (``model_usage[...].contextWindow``); 0 if unknown."""
    if not isinstance(model_usage, dict):
        return 0
    windows = [int(item.get("contextWindow") or 0) for item in model_usage.values() if isinstance(item, dict)]
    return max(windows, default=0)


def map_message(message: Any) -> list[dict[str, Any]]:
    """One SDK message → the job events the chat sees (text deltas, tools, results, retries)."""
    name = type(message).__name__
    if name == "StreamEvent":
        event = getattr(message, "event", {}) or {}
        delta = event.get("delta") if isinstance(event, dict) else None
        if isinstance(delta, dict) and delta.get("type") == "text_delta" and delta.get("text"):
            return [{"kind": "text_delta", "text": str(delta["text"])}]
        return []
    if name == "SystemMessage":
        data = getattr(message, "data", {}) or {}
        subtype = getattr(message, "subtype", "")
        if subtype == "init" and data.get("session_id"):
            event = {"kind": "session", "claude_session_id": str(data["session_id"])}
            if isinstance(data.get("model"), str) and data["model"]:
                event["model"] = data["model"][:200]  # the model this turn really runs with
            return [event]
        if subtype == "api_retry":
            return [{"kind": "api_retry"}]
        if subtype == "compact_boundary":  # the context was compacted: how much (measure first)
            meta = data.get("compact_metadata") if isinstance(data.get("compact_metadata"), dict) else {}
            return [{"kind": "compaction", "trigger": str(meta.get("trigger") or "")[:20],
                     "pre_tokens": int(meta.get("pre_tokens") or 0), "post_tokens": int(meta.get("post_tokens") or 0)}]
        return []
    events: list[dict[str, Any]] = []
    for block in getattr(message, "content", None) or []:
        block_name = type(block).__name__
        if name == "AssistantMessage" and block_name == "TextBlock" and getattr(block, "text", ""):
            events.append({"kind": "text", "text": _clip(block.text, 16000)})
        elif block_name == "ToolUseBlock":
            tool_input = getattr(block, "input", {}) or {}
            event = {"kind": "tool_use", "tool": str(block.name), "tool_use_id": str(block.id),
                     "input_preview": input_preview(str(block.name), tool_input)}
            if diff := change_diff(str(block.name), tool_input):  # the app shows the code change
                event["diff"] = diff
            events.append(event)
        elif block_name == "ToolResultBlock":
            events.append({"kind": "tool_result", "tool_use_id": str(getattr(block, "tool_use_id", "")),
                           "is_error": bool(getattr(block, "is_error", False)),
                           "output": _clip(getattr(block, "content", ""))})
    return events
