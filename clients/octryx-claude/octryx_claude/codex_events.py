"""Codex CLI's JSON events mapped to the platform's turn events, its token usage and its rate limits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .device_sdk_events import _clip, input_preview

# The ChatGPT seat's windows as Codex records them in the thread's rollout (``event_msg`` ``token_count``
# ``rate_limits``, ``limit_id: codex``): ``used_percent``, ``window_minutes``, ``resets_at`` (epoch seconds) for the
# 5-hour (primary) and weekly (secondary) window. ``codex exec --json`` does not print them, so a seat limit's reset
# is read from the rollout.
RATE_LIMIT_ID = "codex"

MAX_ROLLOUT_TAIL = 4 * 1024 * 1024

_WINDOW_KEYS = ("used_percent", "window_minutes", "resets_at")

def rollout_rate_limits(threads: Path, thread_id: str) -> dict[str, Any] | None:
    """``{primary, secondary}`` of the thread's newest recorded seat windows, ``None`` when none is recorded."""
    if not thread_id or "/" in thread_id or not threads.is_dir():
        return None
    files = sorted(threads.glob(f"*/*/*/rollout-*-{thread_id}.jsonl"), key=lambda item: item.stat().st_mtime)
    if not files:
        return None
    try:
        with files[-1].open("rb") as handle:
            handle.seek(max(0, files[-1].stat().st_size - MAX_ROLLOUT_TAIL))
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"rate_limits"' not in line:
            continue
        try:
            payload = json.loads(line).get("payload") or {}
        except (ValueError, AttributeError):
            continue
        limits = payload.get("rate_limits") if isinstance(payload, dict) else None
        if not isinstance(limits, dict) or limits.get("limit_id") not in (None, RATE_LIMIT_ID):
            continue
        windows = {name: {key: window[key] for key in _WINDOW_KEYS if isinstance(window.get(key), (int, float))}
                   for name in ("primary", "secondary") if isinstance(window := limits.get(name), dict)}
        if any("used_percent" in window for window in windows.values()):
            return windows
    return None

def usage_of(raw: Any) -> dict[str, int]:
    """Codex's per-turn usage in the Anthropic keys the platform records (input without the cached part)."""
    usage = raw if isinstance(raw, dict) else {}
    cached = int(usage.get("cached_input_tokens") or 0)
    return {"input_tokens": max(int(usage.get("input_tokens") or 0) - cached, 0),
            "cache_read_input_tokens": cached,
            "cache_creation_input_tokens": int(usage.get("cache_write_input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0)}

def _patch_preview(changes: Any) -> str:
    items = changes if isinstance(changes, list) else []
    shown = (f"{item.get('kind', '?')} {item.get('path', '')}" for item in items if isinstance(item, dict))
    return ", ".join(shown)[:500]

def map_line(row: dict[str, Any]) -> list[dict[str, Any]]:
    """One ``codex exec --json`` line → the job events the chat sees."""
    kind = row.get("type")
    if kind == "thread.started" and row.get("thread_id"):
        return [{"kind": "session", "claude_session_id": str(row["thread_id"])}]
    if kind in ("turn.failed", "error"):
        error = row.get("error") if isinstance(row.get("error"), dict) else {}
        return [{"kind": "error", "message": _clip(str(error.get("message") or row.get("message") or ""), 2000)}]
    item = row.get("item") if isinstance(row.get("item"), dict) else None
    if item is None:
        return []
    item_type, item_id = item.get("type"), str(item.get("id") or "")
    if kind == "item.completed" and item_type == "agent_message" and item.get("text"):
        return [{"kind": "text", "text": _clip(item["text"], 16000)}]
    if item_type == "command_execution":
        if kind == "item.started":
            command_text = str(item.get("command") or "")
            return [{"kind": "tool_use", "tool": "Bash", "tool_use_id": item_id,
                     "input_preview": input_preview("Bash", {"command": command_text})}]
        if kind == "item.completed":
            failed = item.get("status") in ("failed", "declined") or int(item.get("exit_code") or 0) != 0
            return [{"kind": "tool_result", "tool_use_id": item_id, "is_error": failed,
                     "output": _clip(item.get("aggregated_output", ""))}]
    if item_type == "file_change" and kind == "item.completed":
        return [{"kind": "tool_use", "tool": "apply_patch", "tool_use_id": item_id,
                 "input_preview": _patch_preview(item.get("changes"))},
                {"kind": "tool_result", "tool_use_id": item_id, "is_error": item.get("status") == "failed",
                 "output": ""}]
    if item_type == "mcp_tool_call":
        tool = f"mcp__{item.get('server', '')}__{item.get('tool', '')}"
        if kind == "item.started":
            arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
            return [{"kind": "tool_use", "tool": tool, "tool_use_id": item_id,
                     "input_preview": input_preview(tool, arguments)}]
        if kind == "item.completed":
            return [{"kind": "tool_result", "tool_use_id": item_id, "is_error": item.get("status") == "failed",
                     "output": _clip(json.dumps(item.get("result"), ensure_ascii=False)
                                     if item.get("result") is not None else "")}]
    return []
