"""The words of a shell command that ``local_tests`` lets run outside the sandbox: tokens, segments, prefixes, the
test runners, the repository's declared test commands and the read-only stages after a pipe. Stdlib only.
"""

from __future__ import annotations

import base64
import binascii
import os
import posixpath
import re
import shlex
from pathlib import Path
from typing import Any

WRAPPER_VERB = "test-run"
_DISCARD = re.compile(r"(?<!\S)(?:2>&1|[12]?>\s*/dev/null|&>\s*/dev/null)(?!\S)")
_OPERATORS = frozenset({"&&", "||", "|", ";"})
_PYTHON = re.compile(r"^python(?:\d+(?:\.\d+)?)?$")
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
_REFUSED_ASSIGNMENT = re.compile(r"^(?:DYLD_|LD_|BASH_ENV$|ENV$|SHELLOPTS$|PS4$)")
_DURATION = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")
_NUMBER = re.compile(r"^[+-]?\d+$")
READERS = frozenset({"tail", "head", "grep", "egrep", "sort", "uniq", "wc", "cut", "tr", "cat"})
_GREP_REFUSED = frozenset({"-f", "--file", "-r", "-R", "--recursive", "--dereference-recursive", "-d",
                           "--directories"})
_WRAPPED = re.compile(r"^(?P<shim>'[^']+'|\S+) " + WRAPPER_VERB + r" (?P<payload>[A-Za-z0-9_=-]+)$")


# The exit status a test run reports after a pipe: ``echo "exit=${PIPESTATUS[0]}"`` or ``echo $?``, so
# ``python -m pytest -v tests/system 2>&1 | tail -30; echo "exit=${PIPESTATUS[0]}"`` is a test run despite its ``$``.
# Only these exact expansions, and only
# as arguments of ``echo``: they read a status, never a variable or a command.
_STATUS = re.compile(r"\$\{PIPESTATUS\[\d\]\}|\$\?")
STATUS_WORD = "\x00status\x00"


def _tokens(command: str) -> list[str] | None:
    text = _STATUS.sub(STATUS_WORD, str(command or ""))
    if not text.strip() or "$" in text or "`" in text or "\n" in text or "\\" in text:
        return None
    lexer = shlex.shlex(_DISCARD.sub(" ", text), posix=True, punctuation_chars=";&|<>()")
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _segments(tokens: list[str]) -> list[tuple[str, list[str]]] | None:
    """``[(operator before it, words)]``; ``None`` for any operator but ``&& || | ;``."""
    found: list[tuple[str, list[str]]] = [("", [])]
    for token in tokens:
        if token and set(token) <= set(";&|<>()"):
            if token not in _OPERATORS:
                return None
            found.append((token, []))
            continue
        found[-1][1].append(token)
    return found if all(words for _op, words in found) else None


def _strip_prefixes(words: list[str]) -> list[str] | None:
    """The words without leading environment assignments and a ``timeout`` wrapper; ``None`` if one is refused."""
    index = 0
    while index < len(words) and (match := _ASSIGNMENT.match(words[index])):
        if _REFUSED_ASSIGNMENT.match(match.group(1)):
            return None
        index += 1
    words = words[index:]
    if words and words[0] == "timeout":
        rest = words[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in ("-s", "-k", "--signal", "--kill-after") else rest[1:]
        if not rest or not _DURATION.match(rest[0]):
            return None
        words = rest[1:]
    return words


def runner(words: list[str]) -> bool:
    """pytest or unittest, by any interpreter path."""
    if not words:
        return False
    name = posixpath.basename(words[0])
    if name in ("pytest", "py.test"):
        return True
    return bool(_PYTHON.match(name)) and len(words) >= 3 and words[1] == "-m" and words[2] in ("pytest", "unittest")


# The repository's declared test commands (``.octryx/environment.json`` ``test`` / ``system_test``, and each step of
# its ``lint``) run like
# pytest (inside the sandbox e.g. ``flutter test`` cannot write Flutter's cache). A declared command is the words of
# its first
# segment; never a shell, an interpreter's inline code or a wrapper that runs another command.
ENVIRONMENT_FILE = ".octryx/environment.json"
MAX_ENVIRONMENT_DEPTH = 4
_NEVER_DECLARED = frozenset({"sh", "bash", "zsh", "dash", "fish", "env", "eval", "exec", "xargs", "sudo", "su",
                             "nohup", "nice", "osascript", "open", "curl", "wget", "ssh", "scp", "rm", "mv", "cp"})
_INLINE_CODE = frozenset({"-c", "-e", "--eval", "--exec", "-x"})


def _declared_from(text: str) -> list[list[str]]:
    import json  # noqa: PLC0415

    try:
        data = json.loads(text)
    except ValueError:
        return []
    found = []
    for key in ("test", "system_test", "lint"):
        raw = data.get(key) if isinstance(data, dict) else None
        command = raw[0] if isinstance(raw, list) and raw else raw
        tokens = _tokens(str(command or ""))
        segments = _segments(tokens) if tokens else None
        # The declared lint runs like the tests (`flutter analyze` failed in
        # the sandbox, "engine.stamp.tmp: Operation not permitted", and the agent took it for its blocker). Each `&&`
        # step of it on its own; a test command is its first segment.
        steps = [raw_words for operator, raw_words in segments or [] if operator in ("", "&&")] if key == "lint" \
            else [segments[0][1]] if segments else []
        for step in steps:
            words = _strip_prefixes(step)
            if not words or posixpath.basename(words[0]) in _NEVER_DECLARED or any(
                    word in _INLINE_CODE for word in words):
                continue
            found.append(words)
    return found


def declared_commands(root: str, pinned: dict[str, Any] | None = None) -> list[list[str]]:
    """The declared test commands of every environment file in the repository (up to a few folders deep); with the
    run's pinned environment file (``environment_pin``, the run's contract) only its commands: a file the agent
    rewrote never decides what runs outside the sandbox."""
    if isinstance(pinned, dict) and isinstance(pinned.get("environment"), dict):
        import json  # noqa: PLC0415

        return _declared_from(json.dumps(pinned["environment"]))
    if not root or not os.path.isdir(root):
        return []
    found: list[list[str]] = []
    base = root.rstrip("/")
    for folder, dirs, files in os.walk(base):
        depth = folder[len(base):].count("/")
        dirs[:] = [name for name in dirs if not name.startswith(".") or name == ".octryx"] if depth < \
            MAX_ENVIRONMENT_DEPTH else []
        dirs[:] = [name for name in dirs if name not in ("node_modules", "build", ".dart_tool", ".venv", "venv")]
        if folder.endswith("/.octryx") and "environment.json" in files:
            try:
                with open(os.path.join(folder, "environment.json"), encoding="utf-8") as handle:
                    found += _declared_from(handle.read(64_000))
            except OSError:
                continue
    return found


def declared_runner(words: list[str], root: str, pinned: dict[str, Any] | None = None) -> bool:
    """``words`` start with a declared test command; its further words are options or paths inside the repository.

    A declared command that starts with a Python interpreter also matches another Python interpreter running the same
    words after it (:func:`_python_word`): declared ``.venv/bin/python system_test/run_system_test.py`` or
    ``python3 …``, typed ``python system_test/run_system_test.py``. Only the interpreter word may differ: the
    script and every further word are the declared ones, so ``python -c …`` or another script stays inside."""
    for declared in declared_commands(root, pinned):
        if _python_word(declared[0], root) and len(declared) > 1 and words and _python_word(words[0], root):
            same = words[1:len(declared)] == declared[1:]
        else:
            same = words[:len(declared)] == declared
        if same and all(
                arg.startswith("-") or _inside(arg, root) for arg in words[len(declared):]):
            return True
    return False


def _python_word(word: str, root: str) -> bool:
    """``word`` names a Python interpreter: ``python``, ``python3``, ``python3.12`` from ``PATH``, or one in a ``bin``
    folder inside the repository (``.venv/bin/python``)."""
    if not _PYTHON.match(posixpath.basename(word)):
        return False
    if "/" not in word:
        return True
    return posixpath.basename(posixpath.dirname(posixpath.normpath(word))) == "bin" and _inside(word, root)


def _inside(path: str, root: str) -> bool:
    if not path.startswith("/"):
        return ".." not in path.split("/") and not path.startswith("~")
    if not root:
        return False
    target, base = posixpath.normpath(path), posixpath.normpath(root)
    return target == base or target.startswith(base.rstrip("/") + "/")


def _reader(words: list[str]) -> bool:
    name, args = words[0], words[1:]
    if name not in READERS:
        return False
    if name == "tr":
        return True
    positional = [arg for arg in args if not arg.startswith("-") and not _NUMBER.match(arg)]
    if name in ("grep", "egrep"):
        return len(positional) <= 1 and not any(arg in _GREP_REFUSED or arg.split("=", 1)[0] in _GREP_REFUSED
                                                for arg in args)
    return not positional  # tail, head, sort, uniq, wc, cut, cat: the pipe's input only


def wrap(shim: Path | str, command: str) -> str:
    payload = base64.urlsafe_b64encode(command.encode("utf-8")).decode("ascii")
    return f"{shlex.quote(str(shim))} {WRAPPER_VERB} {payload}"


def excluded_pattern(shim: Path | str) -> str:
    """The session's ``sandbox.excludedCommands`` entry: the wrapper and nothing else."""
    return f"{shlex.quote(str(shim))} {WRAPPER_VERB} *"


def unwrap(command: str) -> str | None:
    """The command a wrapped test run carries, or ``None`` when ``command`` is no wrapped test run."""
    match = _WRAPPED.match(str(command or "").strip())
    if not match or posixpath.basename(match.group("shim").strip("'")) not in ("octryx-claude", "octryx"):
        return None
    try:
        return base64.urlsafe_b64decode(match.group("payload").encode("ascii")).decode("utf-8")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


def names_wrapper(command: str) -> bool:
    """The agent's own command calls the wrapper (only the launcher's hook may produce that form)."""
    return bool(re.search(r"(?:^|[\s/'\";&|(])octryx(?:-claude)?['\"]?\s+" + WRAPPER_VERB + r"\b", command or ""))
