"""The closed configuration of a ``git_repository`` connector. Two fetch modes produce the same revisions; a pass never
mixes two commits."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...ledger.errors import InvalidEvidenceRequestError
from .git_hosts import (
    HOST_BITBUCKET_DATACENTER,
    SHA,
    RepositoryLocation,
    parse_datacenter_repository,
    parse_repository_url,
)
from .git_paths import PathFilter, validate_globs
from .git_snapshot import SnapshotLimits

FETCH_REMOTE_GIT = "remote_git"
FETCH_LOCAL_SNAPSHOT = "local_snapshot"
FETCH_MODES = (FETCH_REMOTE_GIT, FETCH_LOCAL_SNAPSHOT)
HEAD_COMMIT = "head_commit"
HEAD_DIRTY = "head_dirty"
RUN_STATE_KEYS = (HEAD_COMMIT, HEAD_DIRTY)
ACCESS_MODE = "access_mode"
ACCESS_READ_ONLY = "read_only"
ACCESS_READ_WRITE = "read_write"
ACCESS_MODES = (ACCESS_READ_ONLY, ACCESS_READ_WRITE)
HOST_KIND = "host"
HOST_BASE = "host_base"
# Keys a configuration change is not compared on: run state and the agents' access mode.
_NOT_CONTENT_KEYS = (*RUN_STATE_KEYS, ACCESS_MODE)

DEFAULT_MAX_FILES = 2000
MAX_MAX_FILES = 5000
DEFAULT_MAX_FILE_BYTES = 512 * 1024
MIN_MAX_FILE_BYTES = 1024
MAX_MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_REF_CHARS = 100
_REF = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")


def _ref(raw: object) -> str:
    if type(raw) is not str:
        raise InvalidEvidenceRequestError()
    ref = raw.strip()
    if not _REF.fullmatch(ref) or ref.startswith(("-", "/")) or ref.endswith(("/", ".", ".lock")) or ".." in ref:
        raise InvalidEvidenceRequestError()
    # A 40-character hex ref is a commit; upper case is normalized so one commit has one form.
    return ref.lower() if SHA.fullmatch(ref.lower()) else ref


def _bounded(raw: object, default: int, low: int, high: int) -> int:
    value = default if raw is None else raw
    if type(value) is not int or not low <= value <= high:
        raise InvalidEvidenceRequestError()
    return value


def validate_access_mode(raw: object) -> str:
    if raw is None:
        return ACCESS_READ_ONLY
    if raw not in ACCESS_MODES:
        raise InvalidEvidenceRequestError()
    return str(raw)


def repository_location(repository_url: object, *, datacenter_base: str | None = None) -> RepositoryLocation:
    if datacenter_base is not None:
        return parse_datacenter_repository(repository_url, datacenter_base)
    return parse_repository_url(repository_url, known_host_only=True)


def validate_git_scope(
    *,
    fetch_mode: object = None,
    repository_url: object,
    ref: object,
    include_globs: object = None,
    exclude_globs: object = None,
    max_files: object = None,
    max_file_bytes: object = None,
    datacenter_base: str | None = None,
    access_mode: object = None,
) -> dict[str, object]:
    mode = FETCH_REMOTE_GIT if fetch_mode is None else fetch_mode
    if mode != FETCH_REMOTE_GIT:
        # A local snapshot connector is created by its upload, never configured here.
        raise InvalidEvidenceRequestError()
    location = repository_location(repository_url, datacenter_base=datacenter_base)
    scope: dict[str, object] = {
        "fetch_mode": mode,
        "remote": location.url,
        "web_base": location.url,
        "ref": _ref(ref),
        "include_globs": list(validate_globs(include_globs)),
        "exclude_globs": list(validate_globs(exclude_globs)),
        "max_files": _bounded(max_files, DEFAULT_MAX_FILES, 1, MAX_MAX_FILES),
        "max_file_bytes": _bounded(max_file_bytes, DEFAULT_MAX_FILE_BYTES, MIN_MAX_FILE_BYTES, MAX_MAX_FILE_BYTES),
    }
    if datacenter_base is not None:
        scope[HOST_KIND] = HOST_BITBUCKET_DATACENTER
        scope[HOST_BASE] = location.host.web_base if location.host is not None else datacenter_base
    if access_mode is not None:
        scope[ACCESS_MODE] = validate_access_mode(access_mode)
    return scope


def configuration_of(scope: dict) -> dict:
    return {key: value for key, value in scope.items() if key not in _NOT_CONTENT_KEYS}


def carry_run_state(stored: dict, configured: dict) -> dict:
    return {**configured, **{key: stored[key] for key in RUN_STATE_KEYS if key in stored}}


@dataclass(frozen=True, slots=True)
class GitScope:
    location: RepositoryLocation
    ref: str
    limits: SnapshotLimits

    @property
    def pinned_commit(self) -> str | None:
        return self.ref if SHA.fullmatch(self.ref) else None

    @classmethod
    def load(cls, scope: dict) -> GitScope:
        host_kind = scope.get(HOST_KIND)
        if host_kind not in (None, HOST_BITBUCKET_DATACENTER):
            raise InvalidEvidenceRequestError()
        base = str(scope.get(HOST_BASE) or "") if host_kind == HOST_BITBUCKET_DATACENTER else None
        checked = validate_git_scope(
            datacenter_base=base,
            fetch_mode=scope.get("fetch_mode"),
            repository_url=scope.get("remote"),
            ref=scope.get("ref"),
            include_globs=scope.get("include_globs"),
            exclude_globs=scope.get("exclude_globs"),
            max_files=scope.get("max_files"),
            max_file_bytes=scope.get("max_file_bytes"),
        )
        return cls(
            location=repository_location(checked["remote"], datacenter_base=base),
            ref=str(checked["ref"]),
            limits=SnapshotLimits(
                paths=PathFilter(tuple(checked["include_globs"]), tuple(checked["exclude_globs"])),  # type: ignore[arg-type]
                max_files=int(checked["max_files"]),  # type: ignore[arg-type]
                max_file_bytes=int(checked["max_file_bytes"]),  # type: ignore[arg-type]
            ),
        )


__all__ = [
    "ACCESS_MODE",
    "ACCESS_MODES",
    "ACCESS_READ_ONLY",
    "ACCESS_READ_WRITE",
    "HOST_BASE",
    "HOST_KIND",
    "DEFAULT_MAX_FILES",
    "DEFAULT_MAX_FILE_BYTES",
    "FETCH_LOCAL_SNAPSHOT",
    "FETCH_MODES",
    "FETCH_REMOTE_GIT",
    "HEAD_COMMIT",
    "HEAD_DIRTY",
    "RUN_STATE_KEYS",
    "MAX_MAX_FILES",
    "MAX_MAX_FILE_BYTES",
    "GitScope",
    "carry_run_state",
    "configuration_of",
    "repository_location",
    "validate_access_mode",
    "validate_git_scope",
]
