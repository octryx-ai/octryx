"""The JUnit report of the repository's declared test command, attached to its PostToolUse (test-contract semantics).

The run contract names the repository's environment as the run prepared it (``preparation.environment``: its ``test``
command and whether a person declared it). When a Bash call runs exactly that command (the same words) and the
command writes a JUnit report (``--junitxml=<path>`` / ``--junit-xml <path>``, inside the repository), the launcher
notes the report file's state at PreToolUse and, at PostToolUse, attaches the report only when the file changed
during the call (``workflow_run_facts.test_report``): a stale report of an earlier run never counts. The server
prefers it over the command's printed output. Best effort and bounded; the launcher decides nothing.

A JUnit ``classname`` names a module (``tests.test_x``), not a file; the server keys every result by the test file
(``tests/test_x.py::test_y``). The launcher has the folder, so it attaches the test files the report's classnames
can name and that exist (``files``, relative to where the command ran): the server resolves the ids with them and
reports any id that stays ambiguous or unknown instead of guessing.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

from .state import LocalState, read_json, write_private_json

STAMPS_FILE = "test_report_stamps.json"
MAX_REPORT_BYTES = 1_000_000
MAX_STAMPS = 20
MAX_HINT_FILES = 500
_CASE = re.compile(r"<testcase\b[^>]*>")
_ATTRIBUTE = re.compile(r'\b(classname|name)="([^"]*)"')
DECLARED_SOURCES = ("declared", "coding_setup")
_JUNIT_OPTIONS = ("--junitxml", "--junit-xml")


def _junit_target(words: list[str]) -> str | None:
    for index, word in enumerate(words):
        for option in _JUNIT_OPTIONS:
            if word.startswith(option + "="):
                return word[len(option) + 1:] or None
            if word == option and index + 1 < len(words):
                return words[index + 1]
    return None


def declared_report(contract: dict[str, Any] | None, hook_input: dict[str, Any], root: Path) -> Path | None:
    """The report file a Bash call of the declared test command writes, inside the repository, else ``None``."""
    environment = ((contract or {}).get("preparation") or {}).get("environment")
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    if hook_input.get("tool_name") != "Bash" or not isinstance(environment, dict) or environment.get(
            "source") not in DECLARED_SOURCES:
        return None
    try:
        words, declared = shlex.split(str(tool_input.get("command") or "")), shlex.split(str(environment.get("test")
                                                                                              or ""))
    except ValueError:
        return None
    target = _junit_target(words) if words and words == declared else None
    if not target:
        return None
    real_root = Path(os.path.realpath(root))
    path = Path(os.path.realpath(Path(str(hook_input.get("cwd") or root)) / target))
    return path if path.is_relative_to(real_root) else None


def hint_files(xml: str, base: Path, root: Path) -> list[str]:
    """The test files the report's classnames (or, for a module that failed to collect, its name) can name: every
    ``a/b.py`` for a prefix ``a.b`` that exists under ``base`` inside ``root``. Bounded; ambiguity is the server's."""
    real_root = Path(os.path.realpath(root))
    found: list[str] = []
    for case in _CASE.findall(xml):
        attributes = dict(_ATTRIBUTE.findall(case))
        parts = (attributes.get("classname") or attributes.get("name") or "").split(".")
        for index in range(len(parts), 0, -1):
            candidate = "/".join(parts[:index]) + ".py"
            if candidate in found or not all(part.isidentifier() for part in parts[:index]):
                continue
            path = Path(os.path.realpath(base / candidate))
            if path.is_relative_to(real_root) and path.is_file():
                found.append(candidate)
        if len(found) >= MAX_HINT_FILES:
            break
    return found[:MAX_HINT_FILES]


def _stamp(path: Path) -> list[int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return [stat.st_mtime_ns, stat.st_size]


def before(state: LocalState, session_key: str, contract: dict[str, Any] | None, hook_input: dict[str, Any],
           root: Path) -> None:
    """PreToolUse: note the report file's state before the declared test command runs."""
    path = declared_report(contract, hook_input, root)
    tool_use_id = str(hook_input.get("tool_use_id") or "")
    if path is None or not tool_use_id:
        return
    file = state.session_dir(session_key) / STAMPS_FILE
    stamps = {key: value for key, value in read_json(file).items() if key != tool_use_id}
    stamps[tool_use_id] = _stamp(path)
    write_private_json(file, dict(list(stamps.items())[-MAX_STAMPS:]))


def attach(state: LocalState, session_key: str, contract: dict[str, Any] | None, hook_input: dict[str, Any],
           root: Path) -> dict[str, Any] | None:
    """PostToolUse: the report the call wrote (``{"format", "path", "junit_xml"}`` and the test ``files`` its
    classnames name), when the file changed."""
    path = declared_report(contract, hook_input, root)
    tool_use_id = str(hook_input.get("tool_use_id") or "")
    file = state.session_dir(session_key) / STAMPS_FILE
    stamps = read_json(file)
    if path is None or tool_use_id not in stamps:
        return None  # no note from before the call: its report cannot be told from an earlier one
    previous = stamps.pop(tool_use_id)
    write_private_json(file, stamps)
    now = _stamp(path)
    if now is None or now == previous or now[1] > MAX_REPORT_BYTES:
        return None
    try:
        text = path.read_bytes()[:MAX_REPORT_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return None
    if "<testcase" not in text:
        return None
    report = {"format": "junit", "path": path.relative_to(Path(os.path.realpath(root))).as_posix(), "junit_xml": text}
    files = hint_files(text, Path(str(hook_input.get("cwd") or root)), root)
    return {**report, "files": files} if files else report


__all__ = ["attach", "before", "declared_report", "hint_files"]
