"""Facts about the app the scenario generator cannot see in the specification of one story.

Without them:

- a ``fresh_profile`` scenario of another feature expected the main list, but a fresh profile first shows the app's
  onboarding: every such scenario was red for the scenario, not the app;
- a scenario expected the app title (its name) as page text at phone width; the title is the window title
  (the stack's ``title_pattern`` finds it in the code) and shows on the page only where a screen renders it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...engineering_knowledge import stacks as stack_data

MAX_SOURCE_FILES = 400


def _hidden_or(names: set[str], relative: Path) -> bool:
    """A path inside a hidden folder (package caches, tool state: not the app) or a named one."""
    return any(part.startswith(".") or part in names for part in relative.parts[:-1])


def _sources(root: Path, facts: dict[str, Any]) -> list[Path]:
    skipped = set(facts.get("skip_folders") or [])
    generated = tuple(facts.get("skip_suffixes") or ())
    return sorted(path for path in root.rglob(str(facts.get("sources") or "")) if path.is_file()
                  and not _hidden_or(skipped, path.relative_to(root))
                  and not (generated and path.name.endswith(generated)))[:MAX_SOURCE_FILES]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def first_start_note(root: Path, catalog: dict[str, str], stacks: dict[str, Any] | None = None) -> str:
    """How a fresh profile starts when the app has a first-start flow (the stack's ``first_start_folder`` or l10n
    keys starting with its ``first_start_key``); ``""`` without one."""
    for facts in stack_data.app_facts(stacks):
        prefix, folder = str(facts.get("first_start_key") or ""), str(facts.get("first_start_folder") or "")
        keys = [key for key in catalog if prefix and key.lower().startswith(prefix)]
        has_folder = bool(folder) and any(path.is_dir() for path in root.rglob(folder)
                                          if not _hidden_or(set(), path.relative_to(root)))
        if not keys and not has_folder:
            continue
        word = str(facts.get("skip_key") or "")
        skip = next((catalog[key] for key in keys if word and word in key.lower()), "")
        leave = f'clicks "{skip}" first' if skip else "goes through it first"
        return ("On a fresh profile (fresh_profile true) this app first shows its onboarding, not its main page. A "
                f"scenario of another feature on a fresh profile {leave}, or uses fresh_profile false with seed "
                "steps; only the onboarding's own scenarios start on it.")
    return ""


def title_note(root: Path, catalog: dict[str, str], stacks: dict[str, Any] | None = None) -> str:
    """The app title is the window title, not proof of a page; ``""`` when the app sets none."""
    for facts in stack_data.app_facts(stacks):
        if not facts.get("title_pattern"):
            continue
        pattern = re.compile(str(facts["title_pattern"]))
        for path in _sources(root, facts):
            match = pattern.search(_read(path))
            if not match:
                continue
            key, literal = ([*match.groups(), "", ""])[:2]
            title = catalog.get(key or "", "") if key else literal
            if title:
                return (f'The app title "{title}" is the browser window title; the page shows it only where a '
                        "screen renders it (e.g. a sidebar on wide screens). Never expect it as proof that a page "
                        "loaded.")
    return ""


__all__ = ["first_start_note", "title_note"]
