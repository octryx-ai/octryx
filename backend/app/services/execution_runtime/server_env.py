"""The environment a server-side command runs with: an allowlist, and git that runs nothing.

The API process carries the platform's secrets in its environment (the database URL, the JWT secret, the encryption
key, OIDC secrets, the pod's IRSA role ``AWS_ROLE_ARN`` / ``AWS_WEB_IDENTITY_TOKEN_FILE``, ``KUBERNETES_*``). A
command an agent runs on the server never inherits it: its environment is built from ``ALLOWED_INHERITED`` (PATH,
HOME, USER, LANG, LC_ALL, TERM, TZ, TMPDIR) plus what the caller sets explicitly (``explicit_env``: a value the caller
merely copied from this process's environment is not explicit and is dropped, so ``{**os.environ, ...}`` reopens
nothing). Only the governed connector paths (kubectl, connector probes) that opt out of the server-build guard keep
the process environment they pass.

``with_git_hardening`` neutralises what a working copy can configure for git to execute (layer 3,
independent of the command classifier and of the file tools): command-line configuration (``GIT_CONFIG_COUNT`` /
``GIT_CONFIG_KEY_n`` / ``GIT_CONFIG_VALUE_n``, which wins over ``.git/config``) sets no hooks, no fsmonitor, ``cat`` as
pager, ``true`` as editor and sequence editor, ``ssh`` in batch mode, no attributes file, no signing, no implicit bare
repository and no ``ext::`` transport; ``GIT_TERMINAL_PROMPT=0``. It appends to configuration a caller already set
(the Git auth of ``git_http_auth``). Not neutralised this way: ``diff.external`` (empty through the environment, git
runs an empty program name; ``safe_git`` passes ``--no-ext-diff``), aliases and filter/merge drivers — for those the
classifier admits only known git subcommands and refuses ``--ext-diff``, and nothing on the server writes ``.git/``.

Git that talks to a remote never asks anyone: credentials come only from the platform's connection,
never from a prompt. ``GIT_TERMINAL_PROMPT=0``; an *inherited* ``GIT_ASKPASS``/``SSH_ASKPASS``/``GIT_SSH_COMMAND`` (the
same value as this process's environment, e.g. a developer's VS Code askpass) and every ``VSCODE_GIT_*`` variable
are removed, while an askpass the connection set explicitly stays; ssh runs with ``BatchMode=yes``. Locally no dialog
opens; on a server, which has none of these, nothing changes.
"""

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
    """The allowlisted part of this process's environment (nothing else of it reaches a server command)."""
    source = os.environ if process_env is None else process_env
    return {key: str(source[key]) for key in ALLOWED_INHERITED if key in source}


def explicit_env(env: Mapping[str, str] | None, *, process_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """What the caller really set: allowlisted keys, and every key whose value differs from this process's."""
    source = os.environ if process_env is None else process_env
    return {str(key): str(value) for key, value in (env or {}).items()
            if key in ALLOWED_INHERITED or source.get(key) != value}


INTERACTIVE_GIT_ENV = ("GIT_ASKPASS", "SSH_ASKPASS", "GIT_SSH_COMMAND")


def _without_inherited_prompts(env: dict[str, str], process_env: Mapping[str, str]) -> dict[str, str]:
    """Drops the askpass and ssh command a developer's shell passed down; keeps one the platform set explicitly."""
    return {key: value for key, value in env.items()
            if not key.startswith("VSCODE_GIT_")
            and not (key in INTERACTIVE_GIT_ENV and process_env.get(key) == value)}


def with_git_hardening(env: Mapping[str, str] | None = None, *,
                       process_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """``env`` plus the git configuration that runs nothing of a working copy (appended to existing ones), and
    git that never prompts (no inherited askpass, ssh in batch mode)."""
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
    """The whole environment of a server command: allowlist + explicit ``env`` + named ``passthrough`` + git."""
    base = inherited_env()
    base.update({key: os.environ[key] for key in passthrough if key in os.environ})
    base.update(explicit_env(env))
    return with_git_hardening(base)


__all__ = ["ALLOWED_INHERITED", "GIT_HARDENING", "INTERACTIVE_GIT_ENV", "explicit_env", "inherited_env",
           "server_command_env", "with_git_hardening"]
