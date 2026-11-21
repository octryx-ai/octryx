"""No foreign build or test tooling, no cloud credentials, no secrets on the Octryx server.

INTERIM MEASURE. This command filter stands in until the sandbox: command-level classification stays bypassable in
principle (a file written by a file tool and later read or run by an allowed tool, a construct the shell parses
differently than this lexer). The real boundary is the sandbox — a Job per run, no API secrets and no IRSA role in
it, an egress allowlist — which is approved and follows. Until then this filter, the allowlisted environment of a
server command (``server_env``), the neutralised git configuration and the audit row of every command
(``command_audit``) narrow what an agent command on the server can reach; none of them is the boundary.

A build or test of a repository runs the repository's own code: Maven plugins, Gradle build scripts, npm lifecycle
scripts, ``setup.py``, ``conftest.py``, Makefile recipes. On the server that code would run inside the API/worker pod,
next to the database credentials, the platform secrets and the pod's cloud role. So the server never runs it: such a
step runs on the owner's device (octryx-claude on the Mac, where nothing here applies), or later in the sandbox.
There is no switch; the guard fails closed.

``classify_command`` judges a command (a shell string or an argv list) segment by segment
(``security_analyzer.command_segments``), after unwrapping what only launches another command (``env``, ``timeout``,
``nice``, ``xargs``, ``find -exec``, ``sh -c``, ``eval`` …). A segment is allowed only when its program is a known
read-only / text / file / git tool (``_ALLOWED_PROGRAMS``) used without an option that executes something. Refused,
each with its class:

- build tools, package managers, test runners, code-loading linters, interpreters, repository scripts;
- cloud and cluster CLIs (kubectl, aws, oc, gcloud, az, helm, vault, docker …: in the pod they act with its IRSA
  role and ServiceAccount) and ``curl``/``wget`` to a metadata address, a cluster or private address or ``file:``;
- reads of the process environment and of mounted secrets (``/proc/<pid>/environ``…, ``/var/run/secrets``, the IRSA
  token, ``env``/``printenv``/``set``/``export -p``/``declare -p``), in an argument or a redirection;
- git beyond its known subcommands (an alias of ``.git/config`` never runs), ``git config`` writes and ``-c`` of keys
  that make git run a program, ``--git-dir``/``--template``;
- any write into ``.git/`` (redirection, ``tee``, ``cp``/``mv``/``ln``/``install``, ``sed -i``, ``dd of=``,
  ``touch``, ``chmod`` …), a write target the lexer cannot judge (``$X``, globs), archive extraction;
- any other program (``unrecognized``: block when in doubt) and a command that cannot be tokenized.

A bare version query of a known build tool (``mvn --version``) runs nothing of the repository and is allowed. The
refusal is ``server_build_not_allowed`` with one plain-English message (``SERVER_BUILD_MESSAGE``); every refusal is
logged (``guard_server_command``) and audited, the workflow-run enforcement points add a run event besides.

The vocabulary lives in ``build_guard_rules``, the classification in ``build_guard_classify`` (with
``build_guard_launchers``, ``build_guard_targets`` and ``build_guard_git``). The server-facing guards stay here and
call ``classify_command`` and ``repository_path_verdict`` through this module, so a test that replaces either here
replaces it for them.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from .build_guard_classify import classify_command
from .build_guard_rules import (
    _GIT_INTERNAL_PATH,
    _SECRET_PATH,
    CLASS_GIT_INTERNALS,
    CLASS_REPOSITORY_PATH,
    CLASS_UNRECOGNIZED,
    SERVER_BUILD_MESSAGE,
    SERVER_BUILD_NOT_ALLOWED,
    ForeignBuildVerdict,
    _blocked,
)

logger = logging.getLogger(__name__)


def cwd_verdict(cwd: Any) -> ForeignBuildVerdict | None:
    """A command whose working directory is inside git's internals (relative writes would land in ``.git/``)."""
    text = str(cwd or "").replace("\\", "/")
    if _GIT_INTERNAL_PATH.search(text) or _SECRET_PATH.search(text):
        return _blocked(CLASS_GIT_INTERNALS, "cwd", f"runs inside git's internals or a secret path ({text[-80:]})")
    return None


def repository_path_verdict(command: str | Sequence[str], path_dirs: Sequence[str]) -> ForeignBuildVerdict | None:
    """A command run with the working copy's own directories first on PATH (a declared ``.venv/bin``): even a
    read-only name (``ruff``, ``git``) would run a file of the repository, so it is refused (``None``: no such PATH)."""
    dirs = [str(item) for item in path_dirs or [] if str(item).strip()]
    if not dirs:
        return None
    words = command.split() if isinstance(command, str) else [str(word) for word in command]
    return _blocked(CLASS_REPOSITORY_PATH, words[0] if words else "",
                    f"PATH starts in the working copy ({', '.join(dirs[:3])})")


def guard_server_command_in(command: str | Sequence[str], path_dirs: Sequence[str], *, where: str,
                            audit: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """``guard_server_command`` for a command that runs with ``path_dirs`` of the working copy first on PATH."""
    if (refusal := guard_server_command(command, where=where, audit=audit)) is not None:
        return refusal
    verdict = repository_path_verdict(command, path_dirs)
    if verdict is None:
        return None
    logger.warning("foreign_build_guard refused a server command: where=%s class=%s detail=%s audit=%s",
                   where, verdict.command_class, verdict.detail, audit or {})
    return refusal_payload(verdict, command=command)


def refusal_payload(verdict: ForeignBuildVerdict, *, command: str | Sequence[str] = "") -> dict[str, Any]:
    """The tool/step result of a refusal: the plain message, the reason code and the auditable verdict."""
    shown = command if isinstance(command, str) else " ".join(str(word) for word in command)
    return {
        "error": SERVER_BUILD_MESSAGE,
        "error_code": SERVER_BUILD_NOT_ALLOWED,
        "code": SERVER_BUILD_NOT_ALLOWED,
        "user_message": SERVER_BUILD_MESSAGE,
        "foreign_build_guard": verdict.to_dict(),
        **({"command": shown[:2000]} if shown else {}),
    }


def guard_server_command(
    command: str | Sequence[str], *, where: str, audit: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The refusal payload when ``command`` may not run on the server (logged with ``where``), else ``None``."""
    verdict = classify_command(command)
    if not verdict.blocked:
        return None
    shown = command if isinstance(command, str) else " ".join(str(word) for word in command)
    logger.warning(
        "foreign_build_guard refused a server command: where=%s class=%s program=%s detail=%s command=%r audit=%s",
        where, verdict.command_class, verdict.program, verdict.detail, shown[:300], audit or {},
    )
    return refusal_payload(verdict, command=command)


def runtime_refusal(result: Any, *, command: str | Sequence[str] = "") -> dict[str, Any] | None:
    """The refusal payload of an ``execute_with_runtime`` result the backstop refused, else ``None``."""
    metadata = getattr(result, "metadata", None) or {}
    if metadata.get("refused") != SERVER_BUILD_NOT_ALLOWED:
        return None
    raw = dict(metadata.get("foreign_build_guard") or {})
    verdict = ForeignBuildVerdict(blocked=True, command_class=str(raw.get("command_class") or CLASS_UNRECOGNIZED),
                                  program=str(raw.get("program") or ""), detail=str(raw.get("detail") or ""))
    return refusal_payload(verdict, command=command)


class ServerBuildNotAllowedError(RuntimeError):
    """Raised where a refusal is an exception, not a result; carries the verdict and the reason code."""

    code = SERVER_BUILD_NOT_ALLOWED

    def __init__(self, verdict: ForeignBuildVerdict) -> None:
        super().__init__(SERVER_BUILD_MESSAGE)
        self.verdict = verdict


__all__ = [
    "ServerBuildNotAllowedError",
    "cwd_verdict",
    "guard_server_command",
    "guard_server_command_in",
    "repository_path_verdict",
    "refusal_payload",
    "runtime_refusal",
]
