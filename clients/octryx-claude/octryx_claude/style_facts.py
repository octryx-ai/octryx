"""What the platform's code style check needs from a changed file, counted on the device (the
platform enforces the style itself, never on the agent's word): the file's lines at the run's base (a file that was
already over the limit only warns unless it grows), its TODO lines and blocks of commented-out code. The server
judges them against the resolved style (``code_style.check``); this module only counts."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

MAX_TODOS = 200
MAX_BLOCKS = 100
MAX_TODO_CHARS = 200
MIN_BLOCK_LINES = 3
_LINE_COMMENT = {".py": "#", ".sh": "#", ".rb": "#", ".yaml": "#", ".yml": "#"}
_SLASH = (".dart", ".ts", ".tsx", ".js", ".jsx", ".kt", ".swift", ".java", ".go", ".c", ".cc", ".cpp", ".rs",
          ".scss", ".cs")
_TODO = re.compile(r"\b(TODO|FIXME)\b")
# A comment line that reads like code: a call, an assignment, a statement end or a block keyword.
_CODE_LIKE = re.compile(r"(\w\s*\(.*\)|[;{}]\s*$|^\s*(return|import|from|def|class|if|for|while|final|var|const|"
                        r"let|await|async|print)\b|\w\s*=\s*\S)")


def _prefix(name: str) -> str | None:
    lower = name.lower()
    if lower.endswith(_SLASH):
        return "//"
    return next((mark for suffix, mark in _LINE_COMMENT.items() if lower.endswith(suffix)), None)


def todos(name: str, text: str) -> list[list[Any]]:
    """``[path, line, text]`` of each TODO / FIXME line."""
    return [[name, number, line.strip()[:MAX_TODO_CHARS]] for number, line in enumerate(text.splitlines(), 1)
            if _TODO.search(line)][:MAX_TODOS]


def commented_code(name: str, text: str) -> list[list[Any]]:
    """``[path, first line, length]`` of each run of at least :data:`MIN_BLOCK_LINES` comment lines that read like
    code (rough on purpose: prose comments rarely end in ``;`` or call something)."""
    mark = _prefix(name)
    if mark is None:
        return []
    blocks: list[list[Any]] = []
    start, run, code = 0, 0, 0
    for number, line in enumerate([*text.splitlines(), ""], 1):
        stripped = line.strip()
        if stripped.startswith(mark) and not stripped.startswith(mark + "/"):  # ``///`` is a doc comment
            start = start or number
            run += 1
            code += bool(_CODE_LIKE.search(stripped[len(mark):]))
            continue
        if run >= MIN_BLOCK_LINES and code * 2 >= run:
            blocks.append([name, start, run])
        start, run, code = 0, 0, 0
    return blocks[:MAX_BLOCKS]


def base_texts(root: Path, base: str, names: list[str], *, timeout: float) -> dict[str, str]:
    """The text of each of ``names`` at ``base`` (files the change modifies); a file new since ``base`` is absent."""
    out: dict[str, str] = {}
    for name in names:
        try:
            shown = subprocess.run(["git", "-C", str(root), "cat-file", "-p", f"{base}:{name}"], capture_output=True,
                                   timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if shown.returncode == 0:
            out[name] = shown.stdout.decode("utf-8", "replace")
    return out


def base_lines(root: Path, base: str, names: list[str], *, timeout: float) -> dict[str, int]:
    """Lines of each of ``names`` at ``base`` (files the change modifies); a file new since ``base`` is absent."""
    return {name: len(text.splitlines()) for name, text in base_texts(root, base, names, timeout=timeout).items()}


__all__ = ["base_lines", "base_texts", "commented_code", "todos"]
