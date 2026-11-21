"""Whether a test command really ran tests. Pure.

A test command is evidence of a test run only when the runner executed tests. Its output decides, never the fact
that a command with a test prefix was issued:

- **ran**: per-test results were parsed (pytest, JUnit XML, Go), or the runner printed its own summary of executed
  tests (pytest ``N passed/failed``, unittest ``Ran N tests``, Jest ``Tests: … total``, Maven ``Tests run: N``,
  ``go test`` ``ok``/``FAIL`` package lines), or it exited 0 (nothing to doubt);
- **environment**: the runner could not start — exit 127/126, ``command not found``, no such executable, the
  runner's own module missing (``No module named pytest`` for ``python3 -m pytest``), or the runner failed while
  loading its configuration (``ImportError while loading conftest``). Nothing the agent wrote can explain this; the
  run pauses ``environment_not_ready`` and no loop iteration is consumed;
- **not_run**: anything else that executed no test — a collection error in a test module, ``no tests ran``, an
  unreadable result. A collection error inside a test module is indistinguishable from a TDD red by import error
  (a test importing what does not exist yet), so it is the agent's to fix: it does not count as a test run (the
  phase's ``run_test_suite`` check fails at Stop), and it never reaches a gate.

The exit code comes from the result (``exit_code``/``returncode``) or Claude Code's ``Exit code N`` first line.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

RAN, ENVIRONMENT, NOT_RUN = "ran", "environment", "not_run"
NOT_RUN_TOOL = "test_command_not_run"
MAX_EXCERPT = 1200

_EXIT = re.compile(r"^\s*Exit code (?P<code>-?\d+)\b", re.MULTILINE)
_SUMMARIES = (
    re.compile(r"\b\d+ (?:passed|failed|xfailed|xpassed)\b"),  # pytest
    re.compile(r"^Ran \d+ tests? in ", re.MULTILINE),  # unittest
    re.compile(r"^Tests:\s+.*\b\d+ total\b", re.MULTILINE),  # Jest / Vitest
    re.compile(r"\bTests run: [1-9]\d*\b"),  # Maven / Gradle
    re.compile(r"^(?:ok|FAIL)\s+\S+\s+[\d.]+s\b", re.MULTILINE),  # go test
    re.compile(r"^\d+:\d+ \+\d+(?: ~\d+)?(?: -\d+)?: (?:All tests passed!|Some tests failed\.)", re.MULTILINE),  # dart
)
_NOT_FOUND = (
    re.compile(r"command not found", re.IGNORECASE),
    re.compile(r"^(?:\S+: )?(?:line \d+: )?\S+: (?:No such file or directory|Permission denied)$", re.MULTILINE),
    re.compile(r"^\S+: (?:no such file or directory|permission denied): \S+$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"is not recognized as an internal or external command", re.IGNORECASE),
)
_NO_MODULE = re.compile(r"No module named ['\"]?(?P<module>[A-Za-z0-9_.]+)")
_RUNNER_CONFIG = re.compile(r"ImportError while loading conftest|error: unrecognized arguments|"
                            r"PluginValidationError|INTERNALERROR", re.IGNORECASE)
_COLLECTION = re.compile(r"errors? during collection|^ERROR collecting ", re.IGNORECASE | re.MULTILINE)
_NO_TESTS = re.compile(r"\bno tests ran\b|\bcollected 0 items\b|\bNo tests found\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TestCommandOutcome:
    kind: str
    reason: str = ""
    exit_code: int | None = None

    def as_dict(self, command: str = "", excerpt: str = "") -> dict[str, Any]:
        return {"kind": self.kind, "reason": self.reason, "exit_code": self.exit_code,
                "command": str(command or "")[:300], "excerpt": str(excerpt or "")[-MAX_EXCERPT:]}


def _exit_code(text: str, result: Mapping[str, Any]) -> int | None:
    raw = result.get("exit_code", result.get("returncode"))
    if type(raw) is int:
        return raw
    match = _EXIT.search(text[:200])
    return int(match["code"]) if match else None


def _runner_module(command: str) -> str | None:
    """``pytest`` for ``pytest …``, ``X`` for ``python -m X …`` (the last segment's runner)."""
    words = str(command or "").replace("&&", ";").split(";")[-1].split()
    for index, word in enumerate(words):
        if word == "-m" and index + 1 < len(words):
            return words[index + 1]
    for word in words:
        name = word.rsplit("/", 1)[-1]
        if "=" not in word and name not in ("env", "uv", "poetry", "run", "pipenv"):
            return name if name.isidentifier() else None
    return None


def classify(result: Mapping[str, Any] | None, *, command: str = "", parsed_results: int = 0) -> TestCommandOutcome:
    """The outcome of one test command from its recorded result (``excerpt`` or ``stdout``/``stderr``)."""
    result = result if isinstance(result, Mapping) else {}
    text = "\n".join(str(result.get(key) or "") for key in ("excerpt", "stdout", "stderr") if result.get(key))
    code = _exit_code(text, result)
    if parsed_results or any(pattern.search(text) for pattern in _SUMMARIES):
        return TestCommandOutcome(RAN, exit_code=code)
    if code in (126, 127) or any(pattern.search(text) for pattern in _NOT_FOUND):
        return TestCommandOutcome(ENVIRONMENT, f"the test runner could not start (exit {code}): "
                                               f"{_first_line(text, _NOT_FOUND) or 'command not found'}", code)
    missing = _NO_MODULE.search(text)
    runner = _runner_module(command)
    if missing and runner and missing["module"].split(".")[0] == runner.split(".")[0]:
        return TestCommandOutcome(ENVIRONMENT, f"the test runner '{runner}' is not installed for this interpreter "
                                               f"({missing.group(0)})", code)
    if _RUNNER_CONFIG.search(text):
        return TestCommandOutcome(ENVIRONMENT, f"the test runner failed while starting: "
                                               f"{_first_line(text, (_RUNNER_CONFIG,))}", code)
    if code == 0 and not _NO_TESTS.search(text):
        return TestCommandOutcome(RAN, exit_code=code)
    if _COLLECTION.search(text):
        return TestCommandOutcome(NOT_RUN, "a test module could not be collected; no test ran (fix the import or "
                                           "syntax error, then run the tests again)", code)
    if _NO_TESTS.search(text):
        return TestCommandOutcome(NOT_RUN, "no tests ran (the command selected no test)", code)
    return TestCommandOutcome(NOT_RUN, "the command reported no test results", code)


def runner_not_started(text: str, code: int | None, command: str) -> str:
    """Why a declared command's runner (a test runner, a linter) could not start, else ``''``: exit 126/127, a
    command-not-found answer, or the runner's own module missing for ``python -m <runner>``."""
    if code in (126, 127) or any(pattern.search(text) for pattern in _NOT_FOUND):
        return f"the runner could not start (exit {code}): {_first_line(text, _NOT_FOUND) or 'command not found'}"
    missing = _NO_MODULE.search(text)
    runner = _runner_module(command)
    if missing and runner and missing["module"].split(".")[0] == runner.split(".")[0]:
        return f"'{runner}' is not installed for this interpreter ({missing.group(0)})"
    return ""


def _first_line(text: str, patterns: Iterable[re.Pattern[str]]) -> str:
    for line in text.splitlines():
        if any(pattern.search(line) for pattern in patterns):
            return line.strip()[:300]
    return ""


def environment_failure(outcomes: Iterable[tuple[TestCommandOutcome, str, str]]) -> dict[str, Any] | None:
    """The newest test command's environment failure (``(outcome, command, excerpt)`` oldest first), if it was one.

    A later test command that ran tests settles it: only the newest decides."""
    newest = None
    for outcome, command, excerpt in outcomes:
        newest = outcome.as_dict(command, excerpt) if outcome.kind == ENVIRONMENT else None
    return newest


def reclassify(uses: Iterable[Any], prefixes: Iterable[Iterable[str]]) -> tuple[list[Any], dict[str, Any] | None]:
    """Chat's tool uses with every test call that ran no test renamed :data:`NOT_RUN_TOOL` (it then counts neither
    as ``run_test_suite`` nor as a test run), and the newest test command's environment failure."""
    from .library import ToolUse
    from .test_output import parse
    from .test_results import TEST_TOOLS, is_test_command

    prefixes = tuple(tuple(item) for item in prefixes)
    kept: list[Any] = []
    seen: list[tuple[TestCommandOutcome, str, str]] = []
    for use in uses:
        shell = is_test_command(use, prefixes)
        if not (use.name in TEST_TOOLS or shell) or not isinstance(use.result, Mapping) or use.result.get("error"):
            kept.append(use)
            continue
        params = use.params if isinstance(use.params, Mapping) else {}
        raw_command = params.get("command") or use.result.get("command") or ""
        # A runner's argv (``run_test_suite``'s ``[python, -m, pytest, …]``) is read as its command line.
        command = " ".join(str(part) for part in raw_command) if isinstance(raw_command, list) else str(raw_command)
        text = "\n".join(str(use.result.get(key) or "") for key in ("stdout", "stderr", "excerpt"))
        report = use.result.get("test_report") if isinstance(use.result.get("test_report"), Mapping) else {}
        fresh = len(report.get("results") or {}) if report.get("fresh") is True else 0  # this execution's report
        outcome = classify(use.result, command=command, parsed_results=max(parse(text).executed(), fresh))
        seen.append((outcome, command, text))
        kept.append(use if outcome.kind == RAN else ToolUse(NOT_RUN_TOOL, False, outcome.as_dict(command, text),
                                                            use.params))
    return kept, environment_failure(seen)


__all__ = ["ENVIRONMENT", "NOT_RUN", "NOT_RUN_TOOL", "RAN", "TestCommandOutcome", "classify",
           "environment_failure", "reclassify", "runner_not_started"]
