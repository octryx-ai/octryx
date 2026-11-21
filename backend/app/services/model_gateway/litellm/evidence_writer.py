"""Write a gateway qualification report to the allowlisted evidence path.

Qualification evidence is operator-facing, so it is written to a file rather than
only logged. That makes the *destination* a security decision: a caller must not be
able to steer the write into the source tree, a deployment manifest, a dotfile, or
anywhere outside the repository. One allowlisted root exists —
``<repo>/evidence/`` (git-ignored)
— and this module refuses everything else.

The payload is validated the same way: the report is already built from the closed
evidence allowlist (``evidence.py``, ``qualification.py``), and this module
re-checks it before writing, rejecting any sensitive-looking key and any string
that could be a URL or an authorization header. A leak therefore has to defeat two
independent structural guards, not one filter.

Some values are admitted by shape rather than by that generic scan, and only
under the closed keys that are *defined* to hold them: a bare host, a rendered
network hop rule, an operator- or cluster-supplied identifier, and a request
path (``evidence_value_shape``). The shared policy matches a credential prefix
as a substring, which is right for free text but refuses an ordinary internal
hostname such as ``litellm.nonprod.example.com``, a cluster model
group such as ``task-router``, and a governance reference such as
``desk-pricing-2026`` — ``desk-``, ``task-`` and ``nonprod`` all contain
``sk-``. A key, a token, an auth header or a credential-bearing URL under those
same keys still fails closed, because none of them has the promised shape.

A refusal names the closed evidence key it came from, so an operator can act on
it. The key is echoed only when it is one of the closed evidence keys, so the
message stays a fixed code plus a known label.

Numbers are checked too: a ``NaN`` or an infinity has no JSON representation, so
it is refused here *and* the encoder runs with ``allow_nan=False``. An evidence
file is read by other tools, and ``NaN``/``Infinity`` are a Python extension
that a strict JSON parser rejects.
"""

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
    """Fixed-code refusal. Carries no path, no payload, and no OS message.

    ``denial_field`` names the closed evidence key the refusal came from, and is
    echoed only when it really is one of those keys — so the message stays a
    fixed code plus a known label, and an operator is not left with a refusal
    that names nothing to fix.
    """

    def __init__(self, denial_reason: str, *, denial_field: str = ""):
        field_name = denial_field if denial_field in ECHOABLE_EVIDENCE_KEYS else ""
        suffix = f" [field={field_name}]" if field_name else ""
        super().__init__(f"Qualification evidence write denied. [reason={denial_reason}]{suffix}")
        self.denial_reason = denial_reason
        self.denial_field = field_name


def resolve_evidence_path(*, repo_root: Any, slug: Any, filename: Any) -> Path:
    """Resolve ``<repo>/evidence/<slug>/<filename>.json``, or refuse.

    Every path component is checked *after* symlink resolution, and the resolved
    evidence root has to still be the canonical ``<repo>/evidence`` under
    the resolved repository root. Resolving the root alone is not enough: it is
    exactly what a symlinked ``evidence`` folder exploits, because the resolved
    target then sits faithfully inside its own resolved parent while both have
    left the repository. Comparing against the constructed canonical location
    instead refuses that, and refuses it before any directory is created.
    """

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


def _write_private_json(target: Path, payload: Mapping[str, Any]) -> str:
    """Create ``target`` through its directory descriptor, or return a denial code.

    ``resolve_evidence_path`` already refuses a symlinked evidence root, slug
    directory or report file — but it decides that on a resolved path, and the
    write happens later. This is the same discipline the CA bundle read applies
    (``ca_bundle._read_bounded_regular_file``), so the check and the write
    cannot describe different filesystem objects:

    - every component below the resolved repository root (``evidence`` and the
      slug) is opened relative to its already-open parent
      with ``O_DIRECTORY|O_NOFOLLOW``; an intermediate symlink swap therefore
      cannot redirect the final open;
    - the report is written to a new private temporary inode and atomically
      renamed relative to the slug descriptor. Existing hardlinks are replaced,
      never truncated, so an allowlisted name cannot modify another inode;
    - ``ELOOP``/``ENOTDIR`` is reported as a path refusal, because that is what a
      symlink appearing under a validated path means.
    """

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
