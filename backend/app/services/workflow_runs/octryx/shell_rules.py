"""The shell an octryx-claude session may use in a workflow run's phase: structure, not string matching."""

from __future__ import annotations

import posixpath
import re
import shlex
from typing import Any

from app.services.agent_gateway.command_strict import strict_argv
from app.services.agent_gateway.command_tokens import Segment

from .pytest_args import _DURATION, _test_path, test_command, without_timeout
from .read_only_commands import _KNOWN_BINARY, _PYTHON_NAME, _command_name, read_only

SHELL_FREE = "free"
SHELL_STRICT = "strict"


def free_shell(phase: dict[str, Any]) -> bool:
    tools = phase.get("tools") or {}
    rules = phase.get("path_rules") or {}
    if rules.get("write") or rules.get("protect_confirmed_tests"):
        return False
    if phase.get("shell") == SHELL_FREE:
        return True
    return ("bash" in set(tools.get("allow") or []) and "bash" not in set(tools.get("deny") or [])
            and phase.get("capability_class") == "deliver")


def workspace_reads(segment: Segment, exec_config: dict[str, Any] | None) -> bool:
    if not exec_config or "diagnosis_read_only_commands" not in exec_config:
        return False
    from ...security_analyzer.builtins import read_only_command_finding

    return read_only_command_finding(shlex.join(segment), exec_config).action == "allow"


_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
# Modules that install, build environments or open an interactive tool: never "the app".
_NOT_AN_APP = frozenset({"pip", "ensurepip", "venv", "virtualenv", "site", "pydoc", "idlelib", "code", "pdb",
                         "pytest", "unittest", "build", "twine", "uv", "poetry", "pipx"})
_APP_SERVERS = frozenset({"uvicorn", "flask", "gunicorn", "hypercorn"})
_LOOPBACK_URL = re.compile(r"^(?:https?://)?(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?(?:[/?#]\S*)?$")
_PROBE_OPTIONS = frozenset({"-s", "-S", "-f", "-i", "-I", "-v", "-L", "-sS", "-fsS", "-sf", "-fs", "-sSf", "-q",
                            "--silent", "--show-error", "--fail", "--include", "--head", "--location", "--verbose",
                            "--compressed", "-O-", "--quiet", "-qO-"})
_PROBE_VALUE_OPTIONS = frozenset({"--max-time", "-m", "--connect-timeout", "-w", "--write-out", "-H", "--header",
                                  "-o", "--output", "--retry", "--retry-delay", "-T", "--timeout", "--tries"})


def _interpreter(word: str) -> bool:
    name = posixpath.basename(word)
    return bool(_PYTHON_NAME.match(name)) and ("/" not in word or bool(_KNOWN_BINARY.match(word))
                                                or ".." not in word.split("/") and not word.startswith(("/", "~")))


def app_start(segment: Segment) -> bool:
    segment = without_timeout(segment)
    if len(segment) < 2:
        return False
    first = segment[0]
    if _interpreter(first):
        if segment[1] == "-m":
            return len(segment) > 2 and bool(_MODULE.match(segment[2])) and segment[2].split(".")[0] not in _NOT_AN_APP
        script = segment[1]
        return script.endswith(".py") and _test_path(script)
    name = posixpath.basename(first)
    in_venv = "/" not in first or (".." not in first.split("/") and not first.startswith(("/", "~")))
    return name in _APP_SERVERS and in_venv and (name != "flask" or "run" in segment[1:3])


def loopback_read(segment: Segment) -> bool:
    name = _command_name(segment)
    if name not in ("curl", "wget"):
        return False
    urls, index, args = 0, 0, list(segment[1:])
    while index < len(args):
        token = args[index]
        option, _sep, value = token.partition("=")
        if option in _PROBE_VALUE_OPTIONS:
            target = value if _sep else (args[index + 1] if index + 1 < len(args) else "")
            if option in ("-o", "--output") and target not in ("/dev/null", "-"):
                return False
            if option in ("-T",) and name == "curl":
                return False
            index += 1 if _sep else 2
            continue
        if token in _PROBE_OPTIONS:
            index += 1
            continue
        if token.startswith("-") or not _LOOPBACK_URL.match(token):
            return False
        urls += 1
        index += 1
    return urls > 0


def _sleep(segment: Segment) -> bool:
    return len(segment) == 2 and segment[0] == "sleep" and bool(_DURATION.match(segment[1]))


def _background(command: str) -> tuple[str, bool]:
    text = str(command or "").rstrip()
    if text.endswith("&") and not text.endswith("&&") and not text.endswith(">&"):
        return text[:-1].rstrip(), True
    return text, False


def strict_shell_allows(command: str, *, runs_tests: bool, test_prefixes: tuple[tuple[str, ...], ...],
                        protected: bool = False, exec_config: dict[str, Any] | None = None) -> bool:
    text, background = _background(command)
    if background and not runs_tests:
        return False
    segments = strict_argv(text)
    if segments is None:
        return False
    if background:
        return all(app_start(segment) or (_command_name(segment) == "cd" and read_only(segment))
                   for segment in segments) and any(app_start(segment) for segment in segments)
    return all(
        read_only(segment) or workspace_reads(segment, exec_config)
        or (runs_tests and (test_command(segment, test_prefixes, protected=protected) or app_start(segment)
                            or loopback_read(segment) or _sleep(segment)))
        for segment in segments)


__all__ = ["SHELL_STRICT", "app_start", "free_shell", "loopback_read", "strict_shell_allows", "workspace_reads"]
