"""How a repository source is named in citations and source lists."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ...ingestion.spans import MAX_DISPLAY_TITLE_CHARS

SCOPE_DISPLAY_NAME = "display_name"
SCOPE_VERSION_LABEL = "version_label"
MAX_NAME_CHARS = 80
MAX_VERSION_CHARS = 40
SHORT_COMMIT_CHARS = 7
REASON_LABEL_INVALID = "repository_label_invalid"

_LABEL = re.compile(r"^[\w.+@/ -]+$")


class RepositoryLabelError(ValueError):
    reason = REASON_LABEL_INVALID


def _label(raw: object, limit: int) -> str | None:
    if raw is None or (type(raw) is str and not raw.strip()):
        return None
    if type(raw) is not str:
        raise RepositoryLabelError()
    text = raw.strip()
    # The character set has no ":" (the title separator) and a name never starts with "/".
    if len(text) > limit or not _LABEL.fullmatch(text) or text.startswith("/"):
        raise RepositoryLabelError()
    return text


def validate_labels(name: object, version: object) -> tuple[str | None, str | None]:
    return _label(name, MAX_NAME_CHARS), _label(version, MAX_VERSION_CHARS)


def with_labels(scope: Mapping[str, Any], name: str | None, version: str | None) -> dict[str, Any]:
    updated = dict(scope)
    if name is not None:
        updated[SCOPE_DISPLAY_NAME] = name
    if version is not None:
        updated[SCOPE_VERSION_LABEL] = version
    return updated


def repository_label(scope: Mapping[str, Any]) -> str:
    name = scope.get(SCOPE_DISPLAY_NAME)
    if isinstance(name, str) and name.strip():
        return name.strip()
    remote = str(scope.get("remote") or "").rstrip("/")
    return remote.rsplit("/", 1)[-1] or "repository"


def file_title(label: str, path: str) -> str:
    titled = f"{label}:{path}"
    return titled if len(titled) <= MAX_DISPLAY_TITLE_CHARS else path


def display_label(scope: Mapping[str, Any]) -> str:
    version = scope.get(SCOPE_VERSION_LABEL)
    commit = scope.get("head_commit")
    parts = [part for part in (
        version.strip() if isinstance(version, str) else "",
        commit[:SHORT_COMMIT_CHARS] if isinstance(commit, str) else "",
    ) if part]
    label = repository_label(scope)
    return f"{label} ({', '.join(parts)})" if parts else label


__all__ = [
    "REASON_LABEL_INVALID",
    "SCOPE_DISPLAY_NAME",
    "SCOPE_VERSION_LABEL",
    "RepositoryLabelError",
    "display_label",
    "file_title",
    "repository_label",
    "validate_labels",
    "with_labels",
]
