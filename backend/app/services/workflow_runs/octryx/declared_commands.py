"""The repository's declared commands: verbatim matches, the app folder, full-suite runs and their outcome."""

from __future__ import annotations

import posixpath
import re
from typing import Any

from app.services.agent_gateway.command_strict import strict_argv
from app.services.agent_gateway.command_tokens import Segment

from .pytest_args import _REPORT_CHARS, _SHORT_FLAGS, without_timeout
from .read_only_commands import _PYTHON_NAME, read_only


def declared_commands(environment: Any) -> tuple[str, ...]:
    # Never a CI-derived proposal.
    from ..workspace.spec import SOURCE_CODING_SETUP, SOURCE_DECLARED, SOURCE_ENVIRONMENT_FILE

    # The repository's own file (``environment_file``) is a person's declaration too: setting the pointer is the
    # opt-in that the file is the law for the Workspace's runs (``workspace/spec``).
    if not isinstance(environment, dict) or environment.get("source") not in (
            SOURCE_DECLARED, SOURCE_CODING_SETUP, SOURCE_ENVIRONMENT_FILE):
        return ()
    return tuple(str(environment.get(key) or "").strip() for key in ("test", "lint", "system_test")
                 if str(environment.get(key) or "").strip())


def declared_command(command: str, declared: tuple[str, ...]) -> bool:
    segments = strict_argv(command)
    return segments is not None and any(strict_argv(item) == segments for item in declared)


def declared_with_readers(command: str, declared: tuple[str, ...]) -> bool:
    # Shell policy only: the evidence still needs the verbatim command, whose exit code a pipe would hide.
    segments = strict_argv(command)
    if not segments:
        return False
    for item in declared:
        expected = strict_argv(item)
        if expected and segments[:len(expected)] == expected and len(segments) > len(expected) and all(
                read_only(segment) for segment in segments[len(expected):]):
            return True
    return False


def declared_part(command: str, declared: tuple[str, ...], app_folder: str = "") -> bool:
    segments = in_app_folder(strict_argv(command), app_folder)
    if not segments:
        return False
    for item in declared:
        parts = [str(item), *(str(item).split("&&") if "&&" in str(item) else [])]
        for part in parts:
            expected = strict_argv(part)
            if expected and segments[:len(expected)] == expected and all(
                    read_only(segment) for segment in segments[len(expected):]):
                return True
    return False


# Options that change only what a run prints or how it stops, never which tests it selects.
_OUTPUT_ONLY = frozenset({"-q", "-qq", "-v", "-vv", "-vvv", "-s", "-x", "-l", "--exitfirst", "--showlocals",
                          "--no-header", "--no-summary", "--disable-warnings", "--quiet", "--verbose", "--ff",
                          "--failed-first", "--capture=no", "--capture=sys", "--capture=fd", "--setup-show",
                          "--strict-markers", "--no-cov", "--color=yes", "--color=no", "--color=auto"})
_OUTPUT_VALUE = frozenset({"--tb", "--maxfail", "--durations", "-n", "--timeout"})


def _runner_args(segment: Segment) -> tuple[str, ...] | None:
    segment = without_timeout(segment)
    if segment and posixpath.basename(segment[0]) in ("pytest", "py.test"):
        return tuple(segment[1:])
    if len(segment) >= 3 and _PYTHON_NAME.match(posixpath.basename(segment[0])) and segment[1:3] == ("-m", "pytest"):
        return tuple(segment[3:])
    return None


def _selection(arguments: tuple[str, ...]) -> tuple[str, ...]:
    kept: list[str] = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        option = token.split("=", 1)[0]
        if token in _OUTPUT_ONLY or _SHORT_FLAGS.match(token) or (token.startswith("-r") and len(token) > 2
                                                                   and _REPORT_CHARS.match(token[2:])):
            index += 1
        elif option in _OUTPUT_VALUE or token == "-r":
            index += 1 if "=" in token else 2
        elif token == "-p" and index + 1 < len(arguments) and arguments[index + 1].startswith("no:"):
            index += 2
        elif token.startswith("-pno:") or (token.startswith("-p") and token[2:].startswith("no:")):
            index += 1
        else:
            kept.append(token)
            index += 1
    return tuple(kept)


def in_app_folder(segments: list[Segment] | None, app_folder: str = "") -> list[Segment] | None:
    folder = posixpath.normpath(str(app_folder or "").strip().rstrip("/") or ".")
    if not segments or folder == "." or len(segments) < 2:
        return segments
    first = segments[0]
    if len(first) == 2 and first[0] == "cd" and posixpath.normpath(first[1].rstrip("/") or ".") == folder:
        return segments[1:]
    return segments


def full_suite_run(command: str, declared: str, app_folder: str = "") -> bool:
    got, want = in_app_folder(strict_argv(command), app_folder), strict_argv(declared)
    if not got or not want or len(got) < len(want):
        return False
    head, rest = got[:len(want)], got[len(want):]
    if any(not read_only(segment) for segment in rest) or head[:-1] != want[:-1]:
        return False
    got_args, want_args = _runner_args(head[-1]), _runner_args(want[-1])
    if want_args is None:
        return without_timeout(head[-1]) == want[-1]
    return got_args is not None and _selection(got_args) == _selection(want_args)


GREEN, RED, UNKNOWN = "green", "red", "unknown"


def run_outcome(command: str, declared: str, *, succeeded: bool, output: str, app_folder: str = "") -> str:
    # A pipe into tail exits 0 whatever the runner said, so the printed summary decides then.
    from .system_tests import summary_counts

    if len(in_app_folder(strict_argv(command), app_folder) or []) <= len(strict_argv(declared) or []):
        return GREEN if succeeded else RED
    counts = summary_counts(output)
    if not counts and (dart := _DART_END.search(str(output or ""))):
        # flutter test / dart test end on "+N ~S -F: All tests passed!" or "Some tests failed."
        return GREEN if succeeded and dart.group("end") == "All tests passed!" and not dart.group("failed") else RED
    if not counts:
        return UNKNOWN if succeeded else RED
    return GREEN if succeeded and counts.get("passed") and not counts.get("failed") and not counts.get(
        "error") else RED


def run_green(command: str, declared: str, *, succeeded: bool, output: str, app_folder: str = "") -> bool:
    return run_outcome(command, declared, succeeded=succeeded, output=output, app_folder=app_folder) == GREEN


_DART_END = re.compile(r"^\d+:\d{2} \+\d+(?: ~\d+)?(?: -(?P<failed>\d+))?: "
                       r"(?P<end>All tests passed!|Some tests failed\.)", re.MULTILINE)
