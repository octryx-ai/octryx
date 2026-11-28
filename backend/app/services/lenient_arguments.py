"""Structured tool arguments a model sent as text (seen with Gemma 4 via Bedrock).
Anything unreadable stays the string, so the tool's own validation still answers."""

from __future__ import annotations

import json
import re
from typing import Any

_OPENERS = {"[": "]", "{": "}"}
_LEADING_JUNK = re.compile(r'\{\s*"?[)\].,\s]*(?=[A-Za-z_][A-Za-z0-9_]*\s*:)')


def _balanced(text: str) -> str | None:
    start = next((index for index, char in enumerate(text) if char in _OPENERS), None)
    if start is None:
        return None
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _quote_keys(text: str) -> str:
    out: list[str] = []
    index, in_string, escaped = 0, False, False
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*(?=\s*:)", text[index:])
        if match and (not out or out[-1].strip() == "" or "".join(out).rstrip()[-1:] in "{,"):
            out.append(f'"{match.group(0)}"')
            index += len(match.group(0))
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _repaired(text: str) -> Any:
    candidate = text.replace('\\"', '"')
    candidate = _LEADING_JUNK.sub("{", candidate)
    block = _balanced(candidate)
    if block is None:
        return None
    for attempt in (block, _quote_keys(block)):
        try:
            return json.loads(attempt)
        except ValueError:
            continue
    return None


def structured(value: Any, *, name: str = "", kind: type = list) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = _repaired(text)
    if isinstance(parsed, dict) and kind is list and name and isinstance(parsed.get(name), list):
        parsed = parsed[name]
    return parsed if isinstance(parsed, kind) else value


def criteria_from_lines(lines: Any) -> list[dict[str, Any]]:
    # A line with fewer than four parts stays as given, so the contract's own validation names what is missing.
    criteria: list[dict[str, Any]] = []
    for line in structured(lines, name="criteria_lines") if isinstance(lines, str) else (lines or []):
        parts = [part.strip() for part in str(line).split("|")]
        if len(parts) < 4:
            criteria.append({"id": parts[0] if parts else "", "text": " | ".join(parts[1:])})
            continue
        ident, text, command, tests = parts[0], parts[1], parts[2], "|".join(parts[3:])
        if command.lower().startswith("manual:"):
            criteria.append({"id": ident, "text": text, "manual_only": True,
                             "manual_reason": command.split(":", 1)[1].strip()})
            continue
        entries = []
        for test in (piece.strip() for piece in tests.split(",")):
            if not test:
                continue
            regression = test.lower().endswith("(regression)")
            entries.append({"id": test[: -len("(regression)")].strip() if regression else test,
                            "role": "regression" if regression else "new"})
        criteria.append({"id": ident, "text": text, "command": command, "tests": entries})
    return criteria


__all__ = ["criteria_from_lines", "structured"]
