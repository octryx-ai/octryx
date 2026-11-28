"""Codex app-server notifications mapped to the platform's turn events, token usage, limit codes and rate limits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .device_sdk_events import _clip, input_preview
from .seat_status import codex_limit_code

# The ChatGPT seat's windows as Codex records them in the thread's rollout (``event_msg`` ``token_count``
# ``rate_limits``, ``limit_id: codex``): ``used_percent``, ``window_minutes``, ``resets_at`` (epoch seconds) for the
# 5-hour (primary) and weekly (secondary) window, read from the rollout after the turn.
RATE_LIMIT_ID = "codex"

MAX_ROLLOUT_TAIL = 4 * 1024 * 1024

_WINDOW_KEYS = ("used_percent", "window_minutes", "resets_at")
_LIMIT_KINDS = {"usageLimitExceeded": "usage_limit", "rateLimitExceeded": "rate_limit"}
_HTTP_KINDS = ("httpConnectionFailed", "responseStreamConnectionFailed")
# The platform keeps the decision's own record; the chat shows only that the call was refused.
DENIED = "Octryx policy denied this tool call."

def rollout_rate_limits(threads: Path, thread_id: str) -> dict[str, Any] | None:
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

def usage_of(last: Any) -> dict[str, int]:
    usage = last if isinstance(last, dict) else {}
    cached = int(usage.get("cachedInputTokens") or 0)
    return {"input_tokens": max(int(usage.get("inputTokens") or 0) - cached, 0),
            "cache_read_input_tokens": cached,
            "cache_creation_input_tokens": int(usage.get("cacheWriteInputTokens") or 0),
            "output_tokens": int(usage.get("outputTokens") or 0)}


def context_of(token_usage: Any) -> dict[str, Any] | None:
    # How full the thread's context is after the last model call: its tokens against the model's window.
    usage = token_usage if isinstance(token_usage, dict) else {}
    last = usage.get("last") if isinstance(usage.get("last"), dict) else {}
    window = int(usage.get("modelContextWindow") or 0)
    used = int(last.get("totalTokens") or 0)
    return {"kind": "context", "used": used, "window": window} if window > 0 and used > 0 else None


def limit_code(error: Any) -> str:
    error = error if isinstance(error, dict) else {}
    info = error.get("codexErrorInfo")
    if isinstance(info, str) and info in _LIMIT_KINDS:
        return _LIMIT_KINDS[info]
    if isinstance(info, dict) and any((info.get(kind) or {}).get("httpStatusCode") == 429 for kind in _HTTP_KINDS):
        return "rate_limit"
    return codex_limit_code({"type": "error", "error": {"message": str(error.get("message") or "")}})


def _patch_preview(changes: Any) -> str:
    items = changes if isinstance(changes, list) else []
    shown = (f"{(item.get('kind') or {}).get('type', '?')} {item.get('path', '')}"
             for item in items if isinstance(item, dict) and isinstance(item.get("kind") or {}, dict))
    return ", ".join(shown)[:500]


def map_item(method: str, item: dict[str, Any]) -> list[dict[str, Any]]:
    kind, item_id = item.get("type"), str(item.get("id") or "")
    started, completed = method == "item/started", method == "item/completed"
    if kind == "agentMessage" and completed and item.get("text"):
        return [{"kind": "text", "text": _clip(str(item["text"]), 16000)}]
    if kind == "commandExecution":
        if started:
            return [{"kind": "tool_use", "tool": "Bash", "tool_use_id": item_id,
                     "input_preview": input_preview("Bash", {"command": str(item.get("command") or "")})}]
        if completed:
            failed = item.get("status") in ("failed", "declined") or int(item.get("exitCode") or 0) != 0
            return [{"kind": "tool_result", "tool_use_id": item_id, "is_error": failed,
                     "output": _clip(str(item.get("aggregatedOutput") or ""))}]
    if kind == "fileChange" and completed:
        return [{"kind": "tool_use", "tool": "apply_patch", "tool_use_id": item_id,
                 "input_preview": _patch_preview(item.get("changes"))},
                {"kind": "tool_result", "tool_use_id": item_id, "is_error": item.get("status") != "completed",
                 "output": ""}]
    if kind == "mcpToolCall":
        tool = f"mcp__{item.get('server', '')}__{item.get('tool', '')}"
        if started:
            arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
            return [{"kind": "tool_use", "tool": tool, "tool_use_id": item_id,
                     "input_preview": input_preview(tool, arguments)}]
        if completed:
            output = item.get("result") if item.get("result") is not None else item.get("error")
            return [{"kind": "tool_result", "tool_use_id": item_id, "is_error": item.get("status") != "completed",
                     "output": _clip(json.dumps(output, ensure_ascii=False) if output is not None else "")}]
    return []


def map_hook(run: dict[str, Any]) -> list[dict[str, Any]]:
    # Codex reports no item for a call its PreToolUse hook blocked; without this the chat would not show it.
    if run.get("eventName") != "preToolUse" or run.get("status") != "blocked":
        return []
    run_id = f"hook-{run.get('id', '')}"
    return [{"kind": "tool_use", "tool": "PreToolUse", "tool_use_id": run_id, "input_preview": "denied by policy"},
            {"kind": "tool_result", "tool_use_id": run_id, "is_error": True, "output": DENIED}]


__all__ = ["context_of", "limit_code", "map_hook", "map_item", "rollout_rate_limits", "usage_of"]
