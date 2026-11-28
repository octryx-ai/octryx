"""Program names and the launchers (``env``, ``timeout``, ``xargs`` …) whose wrapped command is judged."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

from .build_guard_rules import (
    _ASSIGNMENT,
    _INTERPRETERS,
    _SYSTEM_DIRS,
)


def _program_name(word: str) -> tuple[str, bool]:
    if "/" not in word:
        return word, False
    path = PurePosixPath(word)
    if f"{path.parent}/" in _SYSTEM_DIRS and ".." not in path.parts:
        return path.name, False
    return path.name, True


def _interpreter_family(name: str) -> bool:
    return name in _INTERPRETERS or bool(re.fullmatch(r"(python|pypy|ruby|perl|php|node)[0-9.]*", name))


def _skip_options(words: Sequence[str], *, with_value: Iterable[str] = ()) -> int:
    takes_value = set(with_value)
    index = 0
    while index < len(words):
        word = words[index]
        if word == "--":
            return index + 1
        if not word.startswith("-") or word == "-":
            return index
        index += 2 if word in takes_value else 1
    return index


def _unwrap(name: str, args: Sequence[str]) -> list[str] | None:
    if name == "env":
        index = 0
        while index < len(args):
            word = args[index]
            if word in {"-u", "--unset", "-C", "--chdir"}:
                index += 2
            elif word in {"-S", "--split-string"} or word.startswith(("-S", "--split-string=")):
                return ["sh", "-c", " ".join(args[index + 1:]) if word in {"-S", "--split-string"}
                        else word.split("=", 1)[-1] if word.startswith("--") else word[2:]]
            elif word.startswith("-"):
                index += 1
            else:
                break  # assignments stay in front: ``_verdict_for_words`` judges them
        rest = list(args[index:])
        if not [word for word in rest if not _ASSIGNMENT.match(word)]:
            return ["printenv"]  # ``env`` without a command prints the environment
        return rest
    if name in {"nohup", "nocorrect", "builtin", "setsid", "unbuffer", "chronic", "caffeinate"}:
        return list(args[_skip_options(args):])
    if name in {"sudo", "doas"}:
        return list(args[_skip_options(args, with_value={"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"}):])
    if name in {"nice", "ionice", "chrt", "taskset"}:
        return list(args[_skip_options(args, with_value={"-n", "-c", "-p"}):])
    if name == "stdbuf":
        return list(args[_skip_options(args, with_value={"-i", "-o", "-e"}):])
    if name == "time":
        return list(args[_skip_options(args, with_value={"-f", "-o"}):])
    if name == "timeout":
        index = _skip_options(args, with_value={"-s", "--signal", "-k", "--kill-after"})
        return list(args[index + 1:])
    if name == "command":
        if any(word in {"-v", "-V"} for word in args[:2]):
            return []
        return list(args[_skip_options(args):])
    if name == "exec":
        return list(args[_skip_options(args, with_value={"-a"}):])
    if name == "xargs":
        index = _skip_options(args, with_value={"-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a", "--arg-file",
                                                "--delimiter", "--max-args", "--max-procs", "--max-lines"})
        return list(args[index:]) or ["echo"]
    return None
