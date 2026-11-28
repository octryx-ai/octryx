"""Write a gateway qualification report to the allowlisted evidence path ``<repo>/evidence/``."""

from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .evidence_payload_check import ECHOABLE_EVIDENCE_KEYS, inadmissible_payload
from .qualification_report import QualificationReport

EVIDENCE_RELATIVE = Path("evidence")

EVIDENCE_DENIAL_REPO_ROOT_INVALID = "evidence_repo_root_invalid"
EVIDENCE_DENIAL_SLUG_INVALID = "evidence_slug_invalid"
EVIDENCE_DENIAL_FILENAME_INVALID = "evidence_filename_invalid"
EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST = "evidence_path_outside_allowlist"
EVIDENCE_DENIAL_WRITE_FAILED = "evidence_write_failed"

# A slug/filename is an audit label, not a path: no separators, no dots, no case.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_FILENAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
EVIDENCE_SUFFIX = ".json"


class EvidenceWriteDeniedError(Exception):
    """Fixed-code refusal without path, payload or OS message; ``denial_field`` is echoed only when it is a closed
    evidence key."""

    def __init__(self, denial_reason: str, *, denial_field: str = ""):
        field_name = denial_field if denial_field in ECHOABLE_EVIDENCE_KEYS else ""
        suffix = f" [field={field_name}]" if field_name else ""
        super().__init__(f"Qualification evidence write denied. [reason={denial_reason}]{suffix}")
        self.denial_reason = denial_reason
        self.denial_field = field_name


# Every component is checked after symlink resolution against the constructed canonical <repo>/evidence: a symlinked
# evidence folder resolves inside its own resolved parent while both have left the repository, so resolving the root
# alone is not enough.
def resolve_evidence_path(*, repo_root: Any, slug: Any, filename: Any) -> Path:
    if not isinstance(repo_root, (str, Path)) or not str(repo_root).strip():
        raise EvidenceWriteDeniedError(EVIDENCE_DENIAL_REPO_ROOT_INVALID) from None
    root = Path(str(repo_root)).expanduser()
    if not root.is_absolute() or not root.is_dir():
        raise EvidenceWriteDeniedError(EVIDENCE_DENIAL_REPO_ROOT_INVALID) from None
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise EvidenceWriteDeniedError(EVIDENCE_DENIAL_SLUG_INVALID) from None
    if not isinstance(filename, str) or not _FILENAME_RE.match(filename):
        raise EvidenceWriteDeniedError(EVIDENCE_DENIAL_FILENAME_INVALID) from None

    # The repository root is resolved too, so a repository reached through a
    # symlinked parent (a mounted volume, ``/tmp`` on macOS) still matches.
    resolved_root = root.resolve()
    allowlisted_root = (root / EVIDENCE_RELATIVE).resolve()
    if allowlisted_root != resolved_root / EVIDENCE_RELATIVE:
        raise EvidenceWriteDeniedError(EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST) from None
    target = (allowlisted_root / slug / f"{filename}{EVIDENCE_SUFFIX}").resolve()
    # The slug directory and the file get the same treatment, so neither a
    # symlinked ``<slug>`` nor a symlinked report file can relocate the write.
    if target.parent != allowlisted_root / slug:
        raise EvidenceWriteDeniedError(EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST) from None
    return target


def write_qualification_evidence(
    report: QualificationReport,
    *,
    repo_root: Any,
    slug: str,
    filename: str,
) -> Path:
    """Write the closed report payload under the allowlisted evidence path."""

    payload = report.to_evidence()
    denial, denial_field = inadmissible_payload(payload)
    if denial:
        raise EvidenceWriteDeniedError(denial, denial_field=denial_field) from None
    target = resolve_evidence_path(repo_root=repo_root, slug=slug, filename=filename)
    write_denial = _write_private_json(target, payload)
    if write_denial:
        raise EvidenceWriteDeniedError(write_denial) from None
    return target


# Opened relative to already-open parents with O_DIRECTORY|O_NOFOLLOW, so the check and the write describe one object;
# written to a private temporary inode and renamed relative to the slug descriptor, so an existing hardlink is replaced,
# never truncated; ELOOP or ENOTDIR is a path refusal.
def _write_private_json(target: Path, payload: Mapping[str, Any]) -> str:
    if not _descriptor_relative_writes_supported():
        return EVIDENCE_DENIAL_WRITE_FAILED
    if (
        not target.is_absolute()
        or len(target.parents) < 3
        or target.parents[1].name != "evidence"
        or not _SLUG_RE.fullmatch(target.parent.name)
        or not target.name.endswith(EVIDENCE_SUFFIX)
        or not _FILENAME_RE.fullmatch(target.name[: -len(EVIDENCE_SUFFIX)])
    ):
        return EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        repo_directory = os.open(str(target.parents[2]), directory_flags)
        descriptors.append(repo_directory)
        evidence_directory = _open_or_create_directory("evidence", repo_directory, directory_flags)
        descriptors.append(evidence_directory)
        slug_directory = _open_or_create_directory(target.parent.name, evidence_directory, directory_flags)
        descriptors.append(slug_directory)
        os.fchmod(slug_directory, stat.S_IRWXU)
        denial = _write_atomic_private_file(slug_directory, target.name, payload)
    except OSError as error:
        return _path_or_write_denial(error)
    finally:
        for descriptor in reversed(descriptors):
            with contextlib.suppress(OSError):
                os.close(descriptor)
    return denial


def _descriptor_relative_writes_supported() -> bool:
    return all(operation in os.supports_dir_fd for operation in (os.open, os.mkdir, os.rename, os.unlink))


def _open_or_create_directory(name: str, parent: int, flags: int) -> int:
    try:
        os.mkdir(name, stat.S_IRWXU, dir_fd=parent)
    except FileExistsError:
        pass
    return os.open(name, flags, dir_fd=parent)


def _write_atomic_private_file(directory: int, filename: str, payload: Mapping[str, Any]) -> str:
    try:
        existing = os.stat(filename, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        return EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST

    temporary = f".{filename}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    mode = stat.S_IRUSR | stat.S_IWUSR
    try:
        descriptor = os.open(temporary, flags, mode, dir_fd=directory)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            # ``allow_nan=False`` is the structural backstop behind the finite
            # check above: no Python-only literal can reach the file.
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
    except (OSError, ValueError):
        with contextlib.suppress(OSError):
            os.unlink(temporary, dir_fd=directory)
        return EVIDENCE_DENIAL_WRITE_FAILED
    return ""


def _path_or_write_denial(error: OSError) -> str:
    if error.errno in (errno.ELOOP, errno.ENOTDIR):
        return EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST
    # The OS message can carry the resolved path and the running identity, so
    # only the fixed code survives.
    return EVIDENCE_DENIAL_WRITE_FAILED


__all__ = [
    "EVIDENCE_DENIAL_FILENAME_INVALID",
    "EVIDENCE_DENIAL_PATH_OUTSIDE_ALLOWLIST",
    "EVIDENCE_DENIAL_REPO_ROOT_INVALID",
    "EVIDENCE_DENIAL_SLUG_INVALID",
    "EVIDENCE_DENIAL_WRITE_FAILED",
    "EVIDENCE_SUFFIX",
    "EVIDENCE_RELATIVE",
    "EvidenceWriteDeniedError",
    "resolve_evidence_path",
    "write_qualification_evidence",
]
