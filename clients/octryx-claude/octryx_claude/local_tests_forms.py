"""Whether a command is a test run that may leave the sandbox (``local_tests``), with the code style's tools, and the
forms that are one only after a rewrite. Stdlib only.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .local_tests_screens import screenshot
from .local_tests_words import (
    MAX_ENVIRONMENT_DEPTH,
    STATUS_WORD,
    _inside,
    _reader,
    _segments,
    _strip_prefixes,
    _tokens,
    declared_runner,
    runner,
)


# ``mkdir -p tests/system/screenshots && python3 -m playwright screenshot ... tests/system/screenshots/x.png``: a
# ``mkdir`` of folders inside the repository is part of the form, so such a command still runs outside the sandbox.
def _repository_mkdir(args: list[str], root: str) -> bool:
    paths = [arg for arg in args if arg != "-p"]
    return bool(paths) and all(not arg.startswith("-") and _inside(arg, root) for arg in paths)


def _tool_prefix(template: str) -> list[str]:
    """The words of a style tool's command before its first option or placeholder (``dart format``, ``ruff check``)."""
    words = []
    for word in str(template or "").split():
        if word.startswith(("-", "{")):
            break
        words.append(word)
    return words


def style_tools(contract: dict[str, Any] | None) -> list[tuple[list[str], bool]]:
    """``[(prefix, outside_sandbox)]`` of the code style's formatter and linter commands in the run contract
    (``phase.code_style``): the platform's own style check, which the agent may run the same way."""
    phase = contract.get("phase") if isinstance(contract, dict) else None
    style = phase.get("code_style") if isinstance(phase, dict) else None
    languages = style.get("languages") if isinstance(style, dict) else None
    found: list[tuple[list[str], bool]] = []
    for rules in (languages or {}).values() if isinstance(languages, dict) else []:
        for kind in ("formatter", "linter"):
            tool = rules.get(kind) if isinstance(rules, dict) else None
            if not isinstance(tool, dict) or tool.get("enabled") is False:
                continue
            outside = tool.get("outside_sandbox") is True
            templates = [tool.get("command"), tool.get("repo_config_command"),
                         *(item.get("command") for item in tool.get("variants") or [] if isinstance(item, dict))]
            for template in templates:
                prefix = _tool_prefix(str(template or ""))
                if len(prefix) >= 2 and (prefix, outside) not in found:
                    found.append((prefix, outside))
    return found


def style_run(words: list[str], root: str, tools: list[tuple[list[str], bool]] | None) -> bool:
    """``words`` run one of the code style's tools on paths inside the repository (its options as the agent likes)."""
    return any(words[:len(prefix)] == prefix and all(arg.startswith("-") or _inside(arg, root)
                                                    for arg in words[len(prefix):]) for prefix, _ in tools or [])


def is_test_run(command: str, root: str = "", pinned: dict[str, Any] | None = None,
                tools: list[tuple[list[str], bool]] | None = None) -> bool:
    """Whether ``command`` is a test run that may run outside the sandbox (module docstring); with the code style's
    ``tools`` also a run of one of them on its own (inside the sandbox `dart format` cannot write the Dart SDK's
    cache, prints only "Operation not permitted" and changes nothing)."""
    tokens = _tokens(command)
    segments = _segments(tokens) if tokens else None
    if not segments:
        return False
    tests = 0
    for operator, raw in segments:
        if raw[0] != "echo" and any(STATUS_WORD in word for word in raw):
            return False  # a status expansion is only an argument of a plain echo
        if operator == "|":
            if not _reader(raw):
                return False
            continue
        words = _strip_prefixes(raw)
        if not words:
            return False
        if words[0] == "cd":
            if len(words) != 2 or not _inside(words[1], root):
                return False
        elif words[0] == "mkdir":
            if not _repository_mkdir(words[1:], root):
                return False
        elif runner(words) or screenshot(words, root) or declared_runner(words, root, pinned) or style_run(
                words, root, tools):
            tests += 1
        elif words[0] not in ("echo", "true"):
            return False
    return tests > 0


# The forms that cannot leave the sandbox, rewritten to one that can: a test run written to a file
# (``> $TMPDIR/sys.log``) is no test run (a file redirection), so it would run inside the sandbox, where Chromium
# cannot start. A redirection into a file and ``tee`` are dropped; whatever remains must be a test run.
_FILE_REDIRECT = re.compile(r"\s*(?<![<>&\d])(?:&>>?|[12]?>>?)(?!&)\s*(?!/dev/null(?:\s|$))[^\s;&|]+")
_TEE = re.compile(r"\|\s*tee(?:\s+-[a-zA-Z]+)*(?:\s+[^\s;&|]+)*")
_AFTER_FILE = re.compile(r"\s*(?:;|&&)\s*(?:cat|tail|head|grep)\b[^;&|]*$")


def system_test_commands(root: str, pinned: dict[str, Any] | None = None) -> list[str]:
    """The declared system test commands (they start the app and a browser), as declared: the pinned environment
    file's, else every environment file's in the repository."""
    import json  # noqa: PLC0415

    texts: list[str] = []
    if isinstance(pinned, dict) and isinstance(pinned.get("environment"), dict):
        texts = [json.dumps(pinned["environment"])]
    elif root and os.path.isdir(root):
        base = root.rstrip("/")
        for folder, dirs, files in os.walk(base):
            depth = folder[len(base):].count("/")
            dirs[:] = [name for name in dirs if (not name.startswith(".") or name == ".octryx") and name not in (
                "node_modules", "build", ".dart_tool", ".venv", "venv")] if depth < MAX_ENVIRONMENT_DEPTH else []
            if folder.endswith("/.octryx") and "environment.json" in files:
                try:
                    with open(os.path.join(folder, "environment.json"), encoding="utf-8") as handle:
                        texts.append(handle.read(64_000))
                except OSError:
                    continue
    found = []
    for text in texts:
        try:
            raw = json.loads(text).get("system_test")
        except (ValueError, AttributeError):
            continue
        command = raw[0] if isinstance(raw, list) and raw else raw
        if isinstance(command, str) and command.strip():
            found.append(command.strip())
    return found


def compound_system_test(command: str, root: str = "", pinned: dict[str, Any] | None = None) -> str | None:
    """The declared system test when ``command`` runs it among other commands (it would run inside the sandbox,
    where the browser cannot start, and hang until the timeout); ``None`` otherwise, e.g. for
    `python3 - <<'EOF' … EOF …; python3 system_test/run_system_test.py | tail -12`."""
    text = str(command or "")
    if is_test_run(text, root, pinned):
        return None
    return next((declared for declared in system_test_commands(root, pinned) if declared in text), None)


def compound_style_tool(command: str, root: str = "", tools: list[tuple[list[str], bool]] | None = None) -> str | None:
    """The style tool (its command words) when ``command`` runs one that cannot run inside the sandbox among other
    commands; ``None`` otherwise. Such a tool there fails without saying so in a way an agent reads as clean."""
    text = " " + " ".join(str(command or "").split()) + " "
    if is_test_run(str(command or ""), root, tools=tools):
        return None
    return next((" ".join(prefix) for prefix, outside in tools or []
                 if outside and f" {' '.join(prefix)} " in text), None)


def plain_form(command: str, root: str = "") -> str | None:
    """The form of a test run that runs outside the sandbox when ``command`` is one only by writing to a file;
    ``None`` when it is already a test run or no test run at all."""
    text = str(command or "")
    if is_test_run(text, root):
        return None
    plain = _TEE.sub("", text)
    if plain == text and not _FILE_REDIRECT.search(text):
        return None
    plain = _FILE_REDIRECT.sub("", plain)
    plain = _AFTER_FILE.sub("", plain).strip()
    return plain if plain and is_test_run(plain, root) else None
