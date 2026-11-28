"""Segment-by-segment classification of a command; the recursion through launchers and shells."""

from __future__ import annotations

from collections.abc import Sequence

from ..security_analyzer.command_segments import shell_command_segments
from .build_guard_git import _git_verdict
from .build_guard_launchers import _interpreter_family, _program_name, _unwrap
from .build_guard_rules import (
    _ALLOW,
    _ALLOWED_PROGRAMS,
    _ASSIGNMENT,
    _AWK_EXECUTING,
    _BUILD_TOOLS,
    _CLOSING_KEYWORDS,
    _CLOUD_CLIS,
    _CODE_LOADING_LINTERS,
    _ENVIRONMENT_DUMPS,
    _EXECUTING_OPTIONS,
    _EXECUTING_VARIABLE,
    _HEADER_KEYWORDS,
    _HEREDOC,
    _HEREDOC_EXPANSION,
    _MAX_DEPTH,
    _OPENING_KEYWORDS,
    _PACKAGE_MANAGERS,
    _SECRET_PATH,
    _SED_EXECUTING,
    _SHELLS,
    _TEST_RUNNERS,
    _VERSION_FLAGS,
    CLASS_BUILD_TOOL,
    CLASS_CLOUD_CLI,
    CLASS_CODE_LOADING_LINTER,
    CLASS_EXECUTING_OPTION,
    CLASS_INTERPRETER,
    CLASS_PACKAGE_MANAGER,
    CLASS_REPOSITORY_SCRIPT,
    CLASS_SECRET_READ,
    CLASS_TEST_RUNNER,
    CLASS_UNPARSEABLE,
    CLASS_UNRECOGNIZED,
    ForeignBuildVerdict,
    _blocked,
)
from .build_guard_targets import _git_internals_write, _http_verdict, _targets_verdict


def _verdict_for_words(words: Sequence[str], depth: int) -> ForeignBuildVerdict:
    if depth > _MAX_DEPTH:
        return _blocked(CLASS_UNPARSEABLE, "", "command nesting is too deep to judge")
    words = list(words)
    while words and words[0] in _OPENING_KEYWORDS:
        words.pop(0)
    if not words or words[0] in _CLOSING_KEYWORDS or words[0] in _HEADER_KEYWORDS:
        return _ALLOW
    while words and _ASSIGNMENT.match(words[0]):
        variable = _ASSIGNMENT.match(words[0]).group(1)  # type: ignore[union-attr]
        if _EXECUTING_VARIABLE.match(variable):
            return _blocked(CLASS_EXECUTING_OPTION, variable, f"sets {variable}, which can make a tool run a program")
        words.pop(0)
    if not words:
        return _ALLOW
    name, repository_path = _program_name(words[0])
    args = words[1:]
    if (secret := next((word for word in words if _SECRET_PATH.search(word)), None)) is not None:
        return _blocked(CLASS_SECRET_READ, name, f"reads the process environment or a mounted secret ({secret[:80]})")
    if name in _CLOUD_CLIS:
        return _blocked(CLASS_CLOUD_CLI, name, f"{name} acts with the server's cloud/cluster credentials")
    if name in _ENVIRONMENT_DUMPS:
        return _blocked(CLASS_SECRET_READ, name, f"{name} prints the environment")
    if (write := _git_internals_write(name, args)) is not None:
        return write
    if repository_path:
        return _blocked(CLASS_REPOSITORY_SCRIPT, words[0], "runs a file from the working copy")
    launched = _unwrap(name, args)
    if launched is not None:
        return _verdict_for_words(launched, depth + 1) if launched else _ALLOW
    if name in _SHELLS:
        if "-c" in args:
            index = args.index("-c")
            script = args[index + 1] if index + 1 < len(args) else ""
            return classify_command(script, _depth=depth + 1)
        if args and set(args) <= _VERSION_FLAGS | {"--version"}:
            return _ALLOW
        return _blocked(CLASS_REPOSITORY_SCRIPT, name, "runs a shell script")
    if name == "eval":
        return classify_command(" ".join(args), _depth=depth + 1)
    if name in {"source", "."}:
        return _blocked(CLASS_REPOSITORY_SCRIPT, name, "sources a script")
    for command_class, programs in ((CLASS_BUILD_TOOL, _BUILD_TOOLS), (CLASS_PACKAGE_MANAGER, _PACKAGE_MANAGERS),
                                    (CLASS_TEST_RUNNER, _TEST_RUNNERS),
                                    (CLASS_CODE_LOADING_LINTER, _CODE_LOADING_LINTERS)):
        if name in programs:
            return _ALLOW if _version_query(args) else _blocked(command_class, name, f"runs {name}")
    if _interpreter_family(name):
        return _ALLOW if _version_query(args) else _blocked(CLASS_INTERPRETER, name, f"runs {name}")
    if name not in _ALLOWED_PROGRAMS:
        return _blocked(CLASS_UNRECOGNIZED, name, f"{name} is not a known read-only tool")
    return _allowed_program_verdict(name, args, depth)


def _version_query(args: Sequence[str]) -> bool:
    return len(args) == 1 and args[0] in _VERSION_FLAGS


def _allowed_program_verdict(name: str, args: Sequence[str], depth: int) -> ForeignBuildVerdict:
    for option in _EXECUTING_OPTIONS.get(name, ()):
        if any(arg == option or arg.startswith(option + "=") or (len(option) == 2 and arg.startswith(option))
               for arg in args):
            return _blocked(CLASS_EXECUTING_OPTION, name, f"{name} {option} runs another program")
    if name in {"curl", "wget"}:
        return _http_verdict(name, args) or _ALLOW
    if name in {"export", "declare", "typeset", "local", "readonly"} and (
            not [arg for arg in args if not arg.startswith("-")] or "-p" in args):
        return _blocked(CLASS_SECRET_READ, name, f"{name} without a name prints the environment")
    if name == "set" and (not args or args in (["-o"], ["+o"])):
        return _blocked(CLASS_SECRET_READ, name, "set without arguments prints the environment")
    if name in {"export", "declare", "typeset", "local", "readonly"}:
        for arg in args:
            match = _ASSIGNMENT.match(arg)
            if match and _EXECUTING_VARIABLE.match(match.group(1)):
                return _blocked(CLASS_EXECUTING_OPTION, match.group(1),
                                f"sets {match.group(1)}, which can make a tool run a program")
        return _ALLOW
    if name == "find":
        for index, arg in enumerate(args):
            if arg in {"-exec", "-execdir", "-ok", "-okdir"}:
                end = next((i for i in range(index + 1, len(args)) if args[i] in {";", "+", "\\;"}), len(args))
                verdict = _verdict_for_words(args[index + 1:end], depth + 1)
                if verdict.blocked:
                    return verdict
        return _ALLOW
    if name == "git":
        return _git_verdict(args, depth)
    if name in {"awk", "gawk", "mawk", "nawk"}:
        if "-f" in args or any(arg.startswith("--file") for arg in args):
            return _blocked(CLASS_EXECUTING_OPTION, name, f"{name} -f runs a program file")
        if any(_AWK_EXECUTING.search(arg) for arg in args):
            return _blocked(CLASS_EXECUTING_OPTION, name, f"{name} program runs a command")
        return _ALLOW
    if name == "sed":
        if "-f" in args or any(arg.startswith("--file") for arg in args):
            return _blocked(CLASS_EXECUTING_OPTION, name, "sed -f runs a script file")
        if any(_SED_EXECUTING.search(arg) for arg in args if not arg.startswith("-")):
            return _blocked(CLASS_EXECUTING_OPTION, name, "sed e runs a command")
        return _ALLOW
    return _ALLOW


def _without_heredoc_bodies(text: str) -> str | None:
    lines = text.split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        for strip_tabs, quote, delimiter in _HEREDOC.findall(line):
            body: list[str] = []
            while index < len(lines) and (lines[index].lstrip("\t") if strip_tabs else lines[index]) != delimiter:
                body.append(lines[index])
                index += 1
            if index >= len(lines):
                return None
            index += 1
            if not quote and any(_HEREDOC_EXPANSION.search(body_line) for body_line in body):
                return None
    return "\n".join(kept)


def classify_command(command: str | Sequence[str], *, _depth: int = 0) -> ForeignBuildVerdict:
    raw: str | list[str] | None = [str(word) for word in command] if not isinstance(command, str) else command
    if isinstance(raw, str) and "<<" in raw:
        raw = _without_heredoc_bodies(raw)
        if raw is None:
            return _blocked(CLASS_UNPARSEABLE, "", "a here-document runs a command or is not terminated")
    segments = shell_command_segments(raw)
    if segments is None:
        return _blocked(CLASS_UNPARSEABLE, "", "the command cannot be parsed")
    for segment in segments:
        verdict = _targets_verdict(segment.output_targets, segment.input_targets) or _verdict_for_words(
            segment.words, _depth)
        if verdict.blocked:
            return verdict
    return _ALLOW
