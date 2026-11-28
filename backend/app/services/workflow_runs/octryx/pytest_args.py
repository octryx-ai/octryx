"""A Workspace test command with its allow-listed arguments: test paths, node ids and output-only pytest options."""

from __future__ import annotations

import re

from app.services.agent_gateway.command_strict import strict_argv
from app.services.agent_gateway.command_tokens import Segment

from ...agent_gateway.command_match import segment_matches
from .read_only_commands import _command_name

# The test command allow-list (pytest): positional test paths / node ids and these options only — everything else
# (``@argsfile``, ``-p``, ``-c``, ``-o``, ``-W``, ``--pyargs``, ``--basetemp``, ``--rootdir``, …) is refused.
PYTEST_FLAGS = frozenset({"-x", "-q", "-qq", "-v", "-vv", "-vvv", "--lf", "--version", "--co", "--collect-only",
                          "-s", "-l", "--showlocals", "--no-header", "--no-summary", "--disable-warnings",
                          "--capture=no", "--capture=sys", "--capture=fd", "--exitfirst", "--quiet", "--verbose",
                          "--last-failed", "--ff", "--failed-first", "--sw", "--stepwise", "--strict-markers",
                          "--setup-show", "--runxfail", "--no-cov", "--color=yes", "--color=no", "--color=auto"})
PYTEST_VALUE_OPTIONS = frozenset({"-k", "-m", "-r", "--tb", "--maxfail", "--durations", "-n", "--ignore",
                                  "--deselect"})
_SHORT_FLAGS = re.compile(r"^-[xqvsl]{2,}$")  # combined, e.g. ``-xvs``; never ``-qp`` (a plugin)
_NUMBER = re.compile(r"^(?:\d{1,4}|auto|logical)$")
_PATH_OPTIONS = frozenset({"--ignore", "--deselect"})
TB_STYLES = frozenset({"auto", "long", "short", "line", "native", "no"})
_REPORT_CHARS = re.compile(r"^[a-zA-Z]+$")
_TEST_FILE = re.compile(r"^(test_[^/]*\.py|[^/]*_test\.py)$")
_TARGET = re.compile(r"^[A-Za-z0-9_./-]+$")


def _test_target(token: str) -> bool:
    path, _sep, _name = token.partition("::")
    parts = path.split("/")
    if not _TARGET.match(path) or path.startswith(("/", "-")) or ".." in parts:
        return False
    return bool(_TEST_FILE.match(parts[-1])) or ("." not in parts[-1] and not _name)


def _option_value(option: str, value: str) -> bool:
    if not value or value.startswith(("-", "@")):
        return False
    if option == "--tb":
        return value in TB_STYLES
    if option == "-r":
        return bool(_REPORT_CHARS.match(value))
    if option in ("--maxfail", "--durations", "-n"):
        return bool(_NUMBER.match(value))
    if option in _PATH_OPTIONS:
        return _test_path(value)
    return True


def _test_path(token: str) -> bool:
    path = token.partition("::")[0]
    return bool(_TARGET.match(path)) and not path.startswith(("/", "-")) and ".." not in path.split("/")


def _pytest_flag(token: str) -> bool:
    if token in PYTEST_FLAGS or _SHORT_FLAGS.match(token):
        return True
    if token.startswith("-r") and len(token) > 2 and _REPORT_CHARS.match(token[2:]):
        return True
    if token.startswith("-p") and token.removeprefix("-p").strip().startswith("no:"):
        return True  # only switches a plugin off
    option, sep, value = token.partition("=")
    return bool(sep) and option.startswith("--") and option in PYTEST_VALUE_OPTIONS and _option_value(option, value)


def _pytest_arguments(arguments: Segment) -> bool:
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if _pytest_flag(token):
            index += 1
            continue
        if token == "-p":
            value = arguments[index + 1] if index + 1 < len(arguments) else ""
            if not value.startswith("no:"):
                return False
            index += 2
            continue
        if token in PYTEST_VALUE_OPTIONS:
            if not _option_value(token, arguments[index + 1] if index + 1 < len(arguments) else ""):
                return False
            index += 2
            continue
        if not _test_target(token):
            return False
        index += 1
    return True


_DURATION = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")


def without_timeout(segment: Segment) -> Segment:
    if not segment or segment[0] != "timeout":
        return segment
    rest = list(segment[1:])
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in ("-s", "-k", "--signal", "--kill-after") else rest[1:]
    return tuple(rest[1:]) if rest and _DURATION.match(rest[0]) and len(rest) > 1 else segment


def test_command(segment: Segment, test_prefixes: tuple[tuple[str, ...], ...], *, protected: bool = False) -> bool:
    segment = without_timeout(segment)
    if not segment or _command_name(segment) is None:
        return False
    prefix = next((item for item in test_prefixes if segment_matches(segment, item)), None)
    if prefix is None:
        return False
    arguments = segment[len(prefix):]
    if "pytest" in prefix:
        return _pytest_arguments(arguments)
    from ...engineering_knowledge.stacks import runner_options_allowed

    # A runner a stack declares takes its declared harmless options, also in a phase that protects confirmed tests.
    allowed = runner_options_allowed(tuple(prefix), tuple(arguments))
    if allowed is not None:
        return allowed
    return not protected and all(_test_target(token) for token in arguments)


_NAMING = frozenset({"-v", "-vv", "--version", "--co", "--collect-only"})


def pytest_without_test_names(command: str, test_prefixes: tuple[tuple[str, ...], ...]) -> bool:
    segments = strict_argv(command) or []
    for segment in segments:
        prefix = next((item for item in test_prefixes if segment_matches(segment, item)), None)
        if prefix is None or "pytest" not in prefix:
            continue
        arguments = segment[len(prefix):]
        named = any(token in _NAMING or (token.startswith("-r") and ("A" in token[2:] or "p" in token[2:]))
                    for token in arguments)
        if not named:
            return True
    return False
