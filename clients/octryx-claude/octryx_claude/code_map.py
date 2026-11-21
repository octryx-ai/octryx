"""A short map of the run's app, in the first turn's context (cost lever 3).

The token profile of flutter-story 83820a26: 56 model calls, 85k tokens of context each, much of it the agent
finding its way (ls, find, grep over the tree). The launcher has the working copy, so it hands the agent the app's
tracked files once per session: the files whose path names a word of the work item's title first ("likely
relevant"), then the folders with their file counts. Generic: git's own list of tracked files, no stack knowledge.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

MAX_RELEVANT = 15
MAX_FOLDERS = 40
MAX_CHARS = 1800  # with the phase brief (8000) it stays below what Claude Code moves into a file
MIN_WORD = 4
_WORD = re.compile(r"[a-z0-9]+")
MIN_SHARED = 5  # a small app: a word in up to five paths still tells something
MAX_SHARE = 0.25  # a word in more than a quarter of the paths (test, lib, src) tells nothing: no word list in code


def tracked_files(root: str, app_folder: str) -> list[str]:
    """The app's tracked files relative to the repository (``[]`` when git cannot say)."""
    folder = app_folder.strip("/") or "."
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--", folder], capture_output=True, timeout=10,
                             check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [name for name in out.stdout.decode("utf-8", "replace").split("\0") if name]


def _words(title: str) -> set[str]:
    return {word for word in _WORD.findall(title.lower()) if len(word) >= MIN_WORD}


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > MIN_WORD else word


def relevant(files: list[str], title: str) -> list[str]:
    """The files whose path names a word of the title (singular and plural alike), most matches first."""
    lowered_files = [name.lower() for name in files]
    words = {word for word in {_stem(item) for item in _words(title)}
             if sum(1 for name in lowered_files if word in name) <= max(MIN_SHARED, int(len(files) * MAX_SHARE))}
    if not words:
        return []
    scored = []
    for name in files:
        lowered = name.lower()
        hits = sum(1 for word in words if word in lowered)
        if hits:
            scored.append((-hits, len(name), name))
    return [name for _hits, _length, name in sorted(scored)[:MAX_RELEVANT]]


def folders(files: list[str]) -> list[str]:
    counts = Counter(str(PurePosixPath(name).parent) for name in files)
    return [f"{folder}/ ({count})" for folder, count in sorted(counts.items())][:MAX_FOLDERS]


def style_commands(files: list[str], contract: dict[str, Any] | None) -> list[str]:
    """The platform's formatter and linter commands for the languages the app's files are in (``<files>`` for the
    changed files), so the agent runs the same check the platform runs (5a059ed7 / f34f0640)."""
    from .style_tools import EXTENSIONS

    phase = contract.get("phase") if isinstance(contract, dict) else None
    style = phase.get("code_style") if isinstance(phase, dict) else None
    languages = style.get("languages") if isinstance(style, dict) else None
    present = {language for name in files for suffix, language in EXTENSIONS.items() if name.lower().endswith(suffix)}
    found = []
    for language in sorted(present):
        rules = (languages or {}).get(language) if isinstance(languages, dict) else None
        for kind in ("formatter", "linter"):
            tool = dict((rules or {}).get(kind) or {})
            command = str(tool.get("command") or "").strip()
            if command and tool.get("enabled") is not False:
                found.append(command.replace("{files}", "<files>").replace("{platform_config}", "").strip())
    return found


def code_map(root: str, contract: dict[str, Any] | None, head: str, style_head: str = "") -> str:
    """The map's text under ``head`` (a catalog text), or ``""`` without a phase or tracked files."""
    if not isinstance(contract, dict) or not isinstance(contract.get("phase"), dict) or not root:
        return ""
    environment = dict(dict(contract.get("preparation") or {}).get("environment") or {})
    app_folder = str(environment.get("app_folder") or ".")
    files = tracked_files(root, app_folder)
    if not files:
        return ""
    title = str(dict(contract.get("work_item") or {}).get("title") or "")
    lines = [head]
    found = relevant(files, title)
    if found:
        lines += ["Likely relevant (the work item's words in the path):", *(f"- {name}" for name in found)]
    commands = style_commands(files, contract)
    if commands and style_head:
        lines += [style_head.replace("{folder}", app_folder), *(f"- `{command}`" for command in commands)]
    lines += [f"Folders of {app_folder} ({len(files)} tracked files):", *(f"- {row}" for row in folders(files))]
    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS].rsplit("\n", 1)[0]


__all__ = ["code_map", "folders", "relevant", "tracked_files"]
