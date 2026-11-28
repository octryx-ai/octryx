from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"
APP = BACKEND / "app"

_WP = re.compile(r"^WP-[A-Z]{1,2}[0-9]+[a-z]?$")


@dataclass(frozen=True)
class Allowed:
    key: str
    reason: str
    wp: str


@dataclass(frozen=True)
class Accepted:
    key: str
    reason: str


Entry = Allowed | Accepted


def entry_problems(entries: Iterable[Entry]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.key in seen:
            problems.append(f"{entry.key}: listed twice")
        seen.add(entry.key)
        if not entry.reason.strip():
            problems.append(f"{entry.key}: no reason")
        if isinstance(entry, Allowed) and not _WP.match(entry.wp):
            problems.append(f"{entry.key}: work package {entry.wp!r} is not of the form WP-<lane><n>[<phase>]")
    return problems


def counted(occurrences: Counter[str]) -> set[str]:
    return {key if count == 1 else f"{key} (x{count})" for key, count in occurrences.items()}


def comparison_problems(found: Iterable[str], entries: Iterable[Entry], *, what: str) -> list[str]:
    found_set = set(found)
    allowed = {entry.key for entry in entries}
    problems = [f"new {what}: {key}" for key in sorted(found_set - allowed)]
    problems += [f"stale allowlist entry (no longer found, delete it): {key}" for key in sorted(allowed - found_set)]
    return problems


def assert_guard(found: Iterable[str], entries: Iterable[Entry], *, what: str) -> None:
    entries = list(entries)
    problems = entry_problems(entries) + comparison_problems(found, entries, what=what)
    assert not problems, f"{len(problems)} {what} guard problem(s):\n  " + "\n  ".join(problems)

