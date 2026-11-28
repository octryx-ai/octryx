"""Unified-diff hunks: parse them and apply them to a file's lines, reporting a miss as facts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

HUNK_DID_NOT_APPLY = "patch_hunk_did_not_apply"
HUNK_HEADER_INVALID = "patch_hunk_header_invalid"

_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_BODY_PREFIXES = (" ", "-", "+")


@dataclass
class PatchHunk:
    index: int
    old_start: int
    old_count: int
    old_lines: list[str] = field(default_factory=list)
    new_lines: list[str] = field(default_factory=list)


class PatchHunkError(Exception):
    def __init__(self, facts: dict[str, Any]) -> None:
        super().__init__(facts.get("error_code", HUNK_DID_NOT_APPLY))
        self.facts = facts


def is_file_header(lines: list[str], index: int) -> bool:
    return (
        lines[index].startswith("--- ")
        and index + 1 < len(lines)
        and lines[index + 1].startswith("+++ ")
    )


def _body_ends(lines: list[str], index: int) -> bool:
    line = lines[index]
    return line.startswith("@@") or line.startswith("diff --git ") or is_file_header(lines, index)


def parse_hunks(lines: list[str], index: int) -> tuple[list[PatchHunk], int]:
    hunks: list[PatchHunk] = []
    while index < len(lines) and lines[index].startswith("@@"):
        match = _HEADER.match(lines[index])
        number = len(hunks) + 1
        if not match:
            raise PatchHunkError(
                {"error": HUNK_HEADER_INVALID, "error_code": HUNK_HEADER_INVALID, "hunk_index": number}
            )
        index += 1
        body: list[str] = []
        while index < len(lines) and not _body_ends(lines, index):
            body.append(lines[index])
            index += 1
        while body and not body[-1].startswith(_BODY_PREFIXES):
            body.pop()
        hunk = PatchHunk(
            index=number,
            old_start=int(match.group(1)),
            old_count=int(match.group(2)) if match.group(2) is not None else 1,
        )
        for line in body:
            if line.startswith("-"):
                hunk.old_lines.append(line[1:])
            elif line.startswith("+"):
                hunk.new_lines.append(line[1:])
            elif line.startswith(" ") or line == "":
                hunk.old_lines.append(line[1:])
                hunk.new_lines.append(line[1:])
        hunks.append(hunk)
    return hunks, index


def _matches(content: list[str], position: int, expected: list[str]) -> bool:
    if position < 0 or position + len(expected) > len(content):
        return False
    return all(
        content[position + offset].rstrip("\r\n") == line for offset, line in enumerate(expected)
    )


def _miss(hunk: PatchHunk, reason: str, **facts: Any) -> PatchHunkError:
    return PatchHunkError(
        {
            "error": HUNK_DID_NOT_APPLY,
            "error_code": HUNK_DID_NOT_APPLY,
            "hunk_index": hunk.index,
            "expected_line": hunk.old_start,
            "reason": reason,
            **facts,
        }
    )


def _position(content: list[str], hunk: PatchHunk, expected: int) -> int:
    if not hunk.old_lines:
        if 0 <= expected <= len(content):
            return expected
        raise _miss(hunk, "out_of_range", file_lines=len(content))
    if _matches(content, expected, hunk.old_lines):
        return expected
    found = [pos for pos in range(len(content)) if _matches(content, pos, hunk.old_lines)]
    if len(found) == 1:
        return found[0]
    raise _miss(hunk, "context_mismatch" if not found else "ambiguous_context", match_count=len(found))


def apply_hunks(original: list[str], hunks: list[PatchHunk]) -> tuple[list[str], list[dict[str, Any]]]:
    newline = "\r\n" if original and original[0].endswith("\r\n") else "\n"
    content = list(original)
    shift = 0
    applied: list[dict[str, Any]] = []
    for hunk in hunks:
        base = hunk.old_start if not hunk.old_lines else hunk.old_start - 1
        expected = base + shift
        position = _position(content, hunk, expected)
        content[position : position + len(hunk.old_lines)] = [line + newline for line in hunk.new_lines]
        applied.append(
            {"hunk_index": hunk.index, "applied_at_line": position + 1, "offset_lines": position - expected}
        )
        shift += (position - expected) + len(hunk.new_lines) - len(hunk.old_lines)
    return content, applied
