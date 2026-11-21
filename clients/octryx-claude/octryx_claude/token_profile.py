"""Where a turn's tokens went, read from its transcript: one row per model call and one per tool result.

"you should be able to see where tokens could be saved". The turn's ``usage`` (``transcript_usage``)
only says how many tokens a turn used, not what filled the context. This reads the same transcript and reports, per
turn, the facts the platform's token profile is built from (``services/observability/token_profile``):

- ``calls``: per model call ``[input, cache_read, cache_write, output, subagent]``; each message counts once (Claude
  Code writes one line per content block with the same message id);
- ``tools``: per tool result ``[tool_use_id, tool, chars, input_digest, path_digest, call, is_error]``: its full size
  in characters (the job event's ``output`` is cut to 4 KB), a digest of the tool's whole input (the same command or
  read with the same arguments) and of its file path (the same file), and the index of the call that asked for it.
  Digests only, never the input: the event's ``input_preview`` stays the only text of a tool's input;
- ``compactions``: the call index at which the context was compacted;
- ``prompt_chars``: the size of the turn's prompt (the contract or phase prompt the platform sent).

Nothing is priced or judged here; the platform splits the tokens by category and applies its savings rules.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .transcript_streams import STREAM_MAIN
from .turn_idle import _entries

KIND = "token_profile"
# An event body above 64 KB is dropped by the platform (``devices.jobs.bounded_body``); parts stay well below it.
MAX_PART_CHARS = 40_000


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _digest(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]


def _chars(content: Any) -> int:
    """The size of a tool result as the model got it: its text, or the text blocks of a list (an image counts 0)."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(block.get("text") or "") for block in content
                   if isinstance(block, dict) and block.get("type") == "text")
    return 0


def _prompt_chars(message: dict[str, Any]) -> int:
    content = message.get("content")
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list) and not any(isinstance(block, dict) and block.get("type") == "tool_result"
                                             for block in content):
        return _chars(content)
    return 0


def _call_row(usage: dict[str, Any], subagent: bool) -> list[int]:
    return [_count(usage.get("input_tokens")), _count(usage.get("cache_read_input_tokens")),
            _count(usage.get("cache_creation_input_tokens")), _count(usage.get("output_tokens")), int(subagent)]


def turn_profile(streams: dict[str, Path], since: float) -> dict[str, Any] | None:
    """The facts of the messages written at or after ``since``; ``None`` when the turn made no model call."""
    calls: list[list[int]] = []
    tools: list[list[Any]] = []
    compactions: list[int] = []
    asked: dict[str, tuple[str, str, str, int]] = {}
    prompt_chars = 0
    seen: set[str] = set()
    ordered = sorted(streams.items(), key=lambda item: item[0] != STREAM_MAIN)  # the main thread first
    for stream, path in ordered:
        subagent = stream != STREAM_MAIN
        for _when, entry in _entries(path, since):
            message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
            kind = entry.get("type")
            if kind == "system" and entry.get("subtype") == "compact_boundary" and not subagent:
                compactions.append(len(calls))
            elif kind == "assistant":
                key = str(message.get("id") or entry.get("requestId") or entry.get("uuid") or "")
                model = str(message.get("model") or "")
                if (not key or key not in seen) and model and not model.startswith("<") \
                        and isinstance(message.get("usage"), dict):
                    seen.add(key)
                    calls.append(_call_row(message["usage"], subagent))
                if subagent:
                    continue
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id"):
                        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                        path_value = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
                        asked[str(block["id"])] = (str(block.get("name") or "")[:120], _digest(tool_input),
                                                   _digest(path_value) if path_value else "", max(len(calls) - 1, 0))
            elif kind == "user" and not subagent:
                content = message.get("content")
                if not prompt_chars and not entry.get("isMeta"):
                    prompt_chars = _prompt_chars(message)
                for block in content if isinstance(content, list) else []:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_use_id = str(block.get("tool_use_id") or "")
                        tool, digest, path_digest, call = asked.get(tool_use_id, ("", "", "", max(len(calls) - 1, 0)))
                        tools.append([tool_use_id, tool, _chars(block.get("content")), digest, path_digest, call,
                                      int(bool(block.get("is_error")))])
    if not calls:
        return None
    return {"prompt_chars": prompt_chars, "calls": calls, "tools": tools, "compactions": compactions}


def _size(value: Any) -> int:
    return len(json.dumps(value))  # measured like the platform measures it


def events(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """The profile as job events, cut into parts below ``MAX_PART_CHARS``; ``part``/``parts`` put them together."""
    parts: list[dict[str, Any]] = [{"calls": [], "tools": []}]
    for name in ("calls", "tools"):
        for row in profile[name]:
            current = parts[-1]
            if _size(current) + _size(row) > MAX_PART_CHARS:
                current = {"calls": [], "tools": []}
                parts.append(current)
            current[name].append(row)
    return [{"kind": KIND, "part": index, "parts": len(parts), **part,
             **({"prompt_chars": profile["prompt_chars"], "compactions": profile["compactions"]} if index == 0
                else {})} for index, part in enumerate(parts)]


__all__ = ["KIND", "MAX_PART_CHARS", "events", "turn_profile"]
