"""Skill bundles: the file manifest of a version, its digest and the content-addressed blob store.

A bundle is a set of UTF-8 text files with relative POSIX paths (``SKILL.md``, ``references/…``, ``assets/…``,
``scripts/…``, ``LICENSE``). The manifest lists ``{path, sha256, size, kind}`` sorted by path; the bundle digest
is ``sha256:`` over ``path NUL sha256 LF`` of every entry, so it changes when any byte or path changes and does
not depend on order. Limits: 1 MB per file, 5 MB and 200 files per bundle, text only.
"""

from __future__ import annotations

import hashlib
import posixpath
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SkillBlob

MAX_FILE_BYTES = 1_000_000
MAX_BUNDLE_BYTES = 5_000_000
MAX_BUNDLE_FILES = 200

KIND_INSTRUCTIONS = "instructions"
KIND_REFERENCE = "reference"
KIND_ASSET = "asset"
KIND_SCRIPT = "script"
KIND_LICENCE = "licence"
KIND_MANIFEST = "manifest"
FILE_KINDS = (KIND_INSTRUCTIONS, KIND_REFERENCE, KIND_ASSET, KIND_SCRIPT, KIND_LICENCE, KIND_MANIFEST)

SCRIPT_EXTENSIONS = (".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".ps1", ".rb", ".pl")
LICENCE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "COPYING")
MANIFEST_FILES = (".claude-plugin/plugin.json", ".mcp.json")


class BundleError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True, slots=True)
class BundleFile:
    path: str
    content: str
    #: The executable bit of the source file (zip or Git mode 100755); such a file is always a script.
    executable: bool = False

    @property
    def data(self) -> bytes:
        return self.content.encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_path(path: str) -> str:
    """A safe relative POSIX path; refuses absolute paths, ``..``, backslashes and control characters."""
    raw = str(path or "")
    if not raw or "\\" in raw or any(ord(char) < 32 for char in raw):
        raise BundleError("skill_path_invalid", "A file path is empty or contains invalid characters.", path=raw[:200])
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise BundleError("skill_path_absolute", "Absolute paths are not allowed.", path=raw[:200])
    normalized = posixpath.normpath(raw)
    if normalized in {".", "..", ""} or normalized.startswith("../"):
        raise BundleError("skill_path_traversal", "Paths may not leave the skill folder.", path=raw[:200])
    return normalized


def decode_text(path: str, data: bytes) -> str:
    if b"\x00" in data:
        raise BundleError("skill_file_binary", "Only text files are allowed.", path=path)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise BundleError("skill_file_binary", "Only UTF-8 text files are allowed.", path=path) from None


def is_script(path: str, content: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith("scripts/") or name.lower().endswith(SCRIPT_EXTENSIONS) or content.startswith("#!")


def classify(path: str, content: str, executable: bool = False) -> str:
    if executable:
        return KIND_SCRIPT
    if path == "SKILL.md":
        return KIND_INSTRUCTIONS
    if path in LICENCE_FILES:
        return KIND_LICENCE
    if path in MANIFEST_FILES:
        return KIND_MANIFEST
    if is_script(path, content):
        return KIND_SCRIPT
    if path.startswith("assets/"):
        return KIND_ASSET
    return KIND_REFERENCE


def check_limits(files: Iterable[BundleFile]) -> list[BundleFile]:
    listed = list(files)
    if len(listed) > MAX_BUNDLE_FILES:
        raise BundleError("skill_bundle_too_many_files", f"A skill has at most {MAX_BUNDLE_FILES} files.",
                          count=len(listed))
    total = 0
    seen: set[str] = set()
    for item in listed:
        if item.path in seen:
            raise BundleError("skill_path_duplicate", "Two files have the same path.", path=item.path)
        seen.add(item.path)
        size = len(item.data)
        if size > MAX_FILE_BYTES:
            raise BundleError("skill_file_too_large", "A file is larger than 1 MB.", path=item.path, size=size)
        total += size
    if total > MAX_BUNDLE_BYTES:
        raise BundleError("skill_bundle_too_large", "A skill is at most 5 MB.", size=total)
    return listed


def manifest(files: Iterable[BundleFile]) -> list[dict[str, Any]]:
    entries = []
    for item in files:
        entry = {"path": item.path, "sha256": item.sha256, "size": len(item.data),
                 "kind": classify(item.path, item.content, item.executable)}
        if item.executable:
            entry["executable"] = True
        entries.append(entry)
    return sorted(entries, key=lambda entry: entry["path"])


def bundle_digest(entries: Iterable[dict[str, Any]]) -> str:
    hasher = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["path"]):
        hasher.update(f"{entry['path']}\0{entry['sha256']}\n".encode())
    return f"sha256:{hasher.hexdigest()}"


async def store_blobs(db: AsyncSession, files: Iterable[BundleFile]) -> None:
    pending = {item.sha256: item for item in files}
    if not pending:
        return
    existing = set((await db.execute(select(SkillBlob.sha256).where(SkillBlob.sha256.in_(list(pending))))).scalars())
    for sha, item in pending.items():
        if sha not in existing:
            db.add(SkillBlob(sha256=sha, size=len(item.data), content=item.content))
    await db.flush()


async def load_files(db: AsyncSession, entries: Iterable[dict[str, Any]]) -> dict[str, str]:
    """``{path: text}`` of a manifest; a missing blob is a broken invariant and raises."""
    listed = list(entries)
    shas = {entry["sha256"] for entry in listed}
    blobs = {row.sha256: row.content for row in (await db.execute(
        select(SkillBlob).where(SkillBlob.sha256.in_(list(shas))))).scalars()} if shas else {}
    missing = shas - set(blobs)
    if missing:
        raise BundleError("skill_blob_missing", "A file of this version is missing from the blob store.",
                          sha256=sorted(missing)[0])
    return {entry["path"]: blobs[entry["sha256"]] for entry in listed}


async def bundle_files(db: AsyncSession, entries: Iterable[dict[str, Any]]) -> list[BundleFile]:
    """The files of a stored manifest, with their executable bit."""
    listed = list(entries)
    texts = await load_files(db, listed)
    return [BundleFile(entry["path"], texts[entry["path"]], bool(entry.get("executable"))) for entry in listed]


async def load_blob(db: AsyncSession, sha256: str) -> SkillBlob | None:
    return await db.get(SkillBlob, sha256)


__all__ = [
    "FILE_KINDS",
    "KIND_ASSET",
    "KIND_INSTRUCTIONS",
    "KIND_LICENCE",
    "KIND_MANIFEST",
    "KIND_REFERENCE",
    "KIND_SCRIPT",
    "MAX_BUNDLE_BYTES",
    "MAX_BUNDLE_FILES",
    "MAX_FILE_BYTES",
    "BundleError",
    "BundleFile",
    "bundle_digest",
    "bundle_files",
    "check_limits",
    "classify",
    "decode_text",
    "is_script",
    "load_blob",
    "load_files",
    "manifest",
    "normalize_path",
    "sha256_hex",
    "store_blobs",
]
