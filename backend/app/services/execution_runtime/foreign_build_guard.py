"""No foreign build or test tooling, no cloud credentials, no secrets on the Octryx server."""

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
    text = str(cwd or "").replace("\\", "/")
    if _GIT_INTERNAL_PATH.search(text) or _SECRET_PATH.search(text):
        return _blocked(CLASS_GIT_INTERNALS, "cwd", f"runs inside git's internals or a secret path ({text[-80:]})")
    return None


def repository_path_verdict(command: str | Sequence[str], path_dirs: Sequence[str]) -> ForeignBuildVerdict | None:
    dirs = [str(item) for item in path_dirs or [] if str(item).strip()]
    if not dirs:
        return None
    words = command.split() if isinstance(command, str) else [str(word) for word in command]
    return _blocked(CLASS_REPOSITORY_PATH, words[0] if words else "",
                    f"PATH starts in the working copy ({', '.join(dirs[:3])})")


def guard_server_command_in(command: str | Sequence[str], path_dirs: Sequence[str], *, where: str,
                            audit: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if (refusal := guard_server_command(command, where=where, audit=audit)) is not None:
        return refusal
    verdict = repository_path_verdict(command, path_dirs)
    if verdict is None:
        return None
    logger.warning("foreign_build_guard refused a server command: where=%s class=%s detail=%s audit=%s",
                   where, verdict.command_class, verdict.detail, audit or {})
    return refusal_payload(verdict, command=command)


def refusal_payload(verdict: ForeignBuildVerdict, *, command: str | Sequence[str] = "") -> dict[str, Any]:
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
    metadata = getattr(result, "metadata", None) or {}
    if metadata.get("refused") != SERVER_BUILD_NOT_ALLOWED:
        return None
    raw = dict(metadata.get("foreign_build_guard") or {})
    verdict = ForeignBuildVerdict(blocked=True, command_class=str(raw.get("command_class") or CLASS_UNRECOGNIZED),
                                  program=str(raw.get("program") or ""), detail=str(raw.get("detail") or ""))
    return refusal_payload(verdict, command=command)


class ServerBuildNotAllowedError(RuntimeError):
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
