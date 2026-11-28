"""The environment a server-side command runs with: an allowlist, and git that runs nothing."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

ALLOWED_INHERITED = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "TMPDIR")
GIT_HARDENING: tuple[tuple[str, str], ...] = (
    ("core.hooksPath", "/dev/null"),
    ("core.fsmonitor", "false"),
    ("core.pager", "cat"),
    ("core.editor", "true"),
    ("sequence.editor", "true"),
    ("core.sshCommand", "ssh -o BatchMode=yes"),
    ("core.attributesFile", "/dev/null"),
    ("commit.gpgSign", "false"),
    ("tag.gpgSign", "false"),
    ("safe.bareRepository", "explicit"),
    ("protocol.ext.allow", "never"),
)


def inherited_env(process_env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if process_env is None else process_env
    return {key: str(source[key]) for key in ALLOWED_INHERITED if key in source}


def explicit_env(env: Mapping[str, str] | None, *, process_env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if process_env is None else process_env
    return {str(key): str(value) for key, value in (env or {}).items()
            if key in ALLOWED_INHERITED or source.get(key) != value}


INTERACTIVE_GIT_ENV = ("GIT_ASKPASS", "SSH_ASKPASS", "GIT_SSH_COMMAND")


def _without_inherited_prompts(env: dict[str, str], process_env: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in env.items()
            if not key.startswith("VSCODE_GIT_")
            and not (key in INTERACTIVE_GIT_ENV and process_env.get(key) == value)}


def with_git_hardening(env: Mapping[str, str] | None = None, *,
                       process_env: Mapping[str, str] | None = None) -> dict[str, str]:
    result = _without_inherited_prompts(dict(env or {}), os.environ if process_env is None else process_env)
    raw = str(result.get("GIT_CONFIG_COUNT") or "").strip()
    index = int(raw) if raw.isdigit() else 0
    for offset, (key, value) in enumerate(GIT_HARDENING):
        result[f"GIT_CONFIG_KEY_{index + offset}"] = key
        result[f"GIT_CONFIG_VALUE_{index + offset}"] = value
    result["GIT_CONFIG_COUNT"] = str(index + len(GIT_HARDENING))
    result["GIT_TERMINAL_PROMPT"] = "0"
    return result


def server_command_env(env: Mapping[str, str] | None = None, *, passthrough: Iterable[str] = ()) -> dict[str, str]:
    base = inherited_env()
    base.update({key: os.environ[key] for key in passthrough if key in os.environ})
    base.update(explicit_env(env))
    return with_git_hardening(base)


__all__ = ["ALLOWED_INHERITED", "GIT_HARDENING", "INTERACTIVE_GIT_ENV", "explicit_env", "inherited_env",
           "server_command_env", "with_git_hardening"]
