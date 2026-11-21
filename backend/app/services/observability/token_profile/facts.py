"""The facts the savings rules and the top consumers are read from, per scope (pure).

- ``group``: one tool with the same input (the launcher's digest of the whole input; for earlier runs the stored
  preview: the command or the file path): how often, how large, what it cost in all the calls that carried it;
- ``path``: one file read, whatever the arguments (the digest of its path; earlier runs: the path);
- ``job``: one session: the prompt-cache write of its last call, never read again (measured turns only);
- ``phase``: one phase: calls, the average input a call carried (known only when every turn was measured), compactions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .catalog import status_tools
from .split import Split, Turn

LABEL_CHARS = 80


def short_tool(tool: str) -> str:
    """``mcp__server__name`` → ``name``: the tool as a person knows it."""
    return tool.rsplit("__", 1)[-1] if tool.startswith("mcp__") else tool


def _label(tool: str, preview: str) -> str:
    """The tool and its input in one line; a long one keeps its end (a file path's name) and loses its middle."""
    name, text = short_tool(tool), " ".join(preview.split())
    room = LABEL_CHARS - len(name) - 1
    if len(text) > room:
        text = text[:12] + "…" + text[-(room - 13):]
    return f"{name} {text}".strip()


def _kb(chars: int) -> int:
    return (chars + 1023) // 1024


@dataclass
class _Group:
    tool: str
    label: str
    count: int = 0
    max_chars: int = 0
    chars: int = 0
    tokens: int = 0
    estimated: bool = False
    clipped: bool = False

    def row(self, phases: set[str]) -> dict[str, Any]:
        return {"tool": self.tool, "label": self.label, "count": self.count, "max_kb": _kb(self.max_chars),
                "total_kb": _kb(self.chars), "tokens": self.tokens, "estimated": self.estimated,
                "at_least": self.clipped, "status_tool": self.tool in status_tools(),
                "phase": ", ".join(sorted(phase for phase in phases if phase))}


def _grouped(pairs: list[tuple[Turn, Split]], by_path: bool) -> list[dict[str, Any]]:
    groups: dict[str, _Group] = {}
    phases: dict[str, set[str]] = defaultdict(set)
    for turn, split in pairs:
        for result, carried in zip(turn.tools, split.carried, strict=True):
            key = result.path_key if by_path else result.key
            if not key or (by_path and result.tool != "Read"):
                continue
            group = groups.setdefault(key, _Group(result.tool, _label(result.tool, result.label)))
            group.count += 1
            group.max_chars = max(group.max_chars, result.chars)
            group.chars += result.chars
            group.tokens += carried
            group.estimated |= not turn.measured
            group.clipped |= result.clipped
            phases[key].add(turn.node_id)
    return [group.row(phases[key]) for key, group in groups.items()]


def groups(pairs: list[tuple[Turn, Split]]) -> list[dict[str, Any]]:
    return _grouped(pairs, by_path=False)


def paths(pairs: list[tuple[Turn, Split]]) -> list[dict[str, Any]]:
    return _grouped(pairs, by_path=True)


def jobs(pairs: list[tuple[Turn, Split]]) -> list[dict[str, Any]]:
    last: dict[str, Turn] = {}
    for turn, _split in pairs:
        if turn.measured and turn.main_calls:
            last[turn.job_id] = turn
    return [{"job_id": job_id, "phase": turn.node_id, "unused_cache_write_tokens": turn.main_calls[-1].cache_write,
             "tokens": turn.main_calls[-1].cache_write} for job_id, turn in last.items()]


def phases(pairs: list[tuple[Turn, Split]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for turn, split in pairs:
        row = rows.setdefault(turn.node_id, {"phase": turn.node_id or "Unassigned", "calls": 0, "input": 0,
                                             "compactions": 0, "measured": True})
        row["measured"] &= turn.measured  # calls are only known when measured; an estimate guesses them
        row["calls"] += split.calls
        row["input"] += split.cache["read"] + split.cache["write"] + split.cache["uncached"]
        row["compactions"] += len(turn.compactions)
    for row in rows.values():
        row["avg_call_input_tokens"] = row["input"] // row["calls"] if row["calls"] else 0
    return list(rows.values())


SCOPES = {"group": groups, "path": paths, "job": jobs, "phase": phases}

__all__ = ["SCOPES", "groups", "jobs", "paths", "phases", "short_tool"]
