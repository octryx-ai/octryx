"""Reading an uploaded skill: one ``SKILL.md``, or a ``.zip`` holding exactly one skill folder.

Archive safety, refused with fixed codes before anything is stored:

- the upload is at most 5 MB, the archive at most 200 files and 5 MB uncompressed, each file at most 1 MB;
- a compression ratio above 100 (per file or in total) is a zip bomb (``skill_archive_ratio``); sizes are
  enforced while reading, never trusted from the archive header;
- symlinks, absolute paths, ``..``, backslashes, encrypted entries and binary files are refused;
- exactly one ``SKILL.md`` at the root or in one top-level folder; every other file must sit in that folder.

macOS archive metadata (``__MACOSX/``, ``.DS_Store``) is skipped. The executable bit of an entry is kept so the
scanner treats such a file as a script.
"""

from __future__ import annotations

import io
import stat
import zipfile
from dataclasses import dataclass

from .bundle import (
    MAX_BUNDLE_BYTES,
    MAX_BUNDLE_FILES,
    MAX_FILE_BYTES,
    BundleError,
    BundleFile,
    check_limits,
    decode_text,
    normalize_path,
)
from .spec import SKILL_FILE, SkillSpecError, parse_skill_md

MAX_UPLOAD_BYTES = MAX_BUNDLE_BYTES
MAX_RATIO = 100
_SKIPPED_PARTS = ("__MACOSX",)
_SKIPPED_NAMES = (".DS_Store",)
_ZIP_MAGIC = b"PK\x03\x04"


@dataclass(frozen=True, slots=True)
class UploadedSkill:
    folder: str | None
    files: list[BundleFile]


def _skipped(path: str) -> bool:
    parts = path.split("/")
    return parts[0] in _SKIPPED_PARTS or parts[-1] in _SKIPPED_NAMES


def _entry_bytes(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    with archive.open(info) as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise BundleError("skill_file_too_large", "A file is larger than 1 MB.", path=info.filename)
    if info.compress_size and len(data) / max(info.compress_size, 1) > MAX_RATIO:
        raise BundleError("skill_archive_ratio", "The archive is compressed suspiciously well (zip bomb).",
                          path=info.filename)
    return data


def _zip_files(data: bytes) -> list[tuple[str, bytes, bool]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise BundleError("skill_archive_invalid", "The file is not a valid zip archive.") from None
    entries: list[tuple[str, bytes, bool]] = []
    total = 0
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_BUNDLE_FILES + 10:
            raise BundleError("skill_bundle_too_many_files", f"A skill has at most {MAX_BUNDLE_FILES} files.")
        for info in infos:
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise BundleError("skill_archive_symlink", "Symbolic links are not allowed.", path=info.filename)
            if info.flag_bits & 0x1:
                raise BundleError("skill_archive_encrypted", "Encrypted archives are not allowed.",
                                  path=info.filename)
            path = normalize_path(info.filename)
            if _skipped(path):
                continue
            content = _entry_bytes(archive, info)
            total += len(content)
            if total > MAX_BUNDLE_BYTES:
                raise BundleError("skill_bundle_too_large", "A skill is at most 5 MB.")
            entries.append((path, content, bool(mode & 0o111)))
    if total and total / max(len(data), 1) > MAX_RATIO:
        raise BundleError("skill_archive_ratio", "The archive is compressed suspiciously well (zip bomb).")
    return entries


def _skill_root(paths: list[str]) -> str:
    roots = [path[: -len(SKILL_FILE)] for path in paths if path == SKILL_FILE or path.endswith(f"/{SKILL_FILE}")]
    roots = [root for root in roots if root.count("/") <= 1]
    if len(roots) != 1:
        raise BundleError("skill_archive_skill_count", "The archive must hold exactly one skill (one SKILL.md).",
                          found=len(roots))
    root = roots[0]
    outside = [path for path in paths if not path.startswith(root)]
    if outside:
        raise BundleError("skill_archive_outside_folder", "Every file must sit in the skill folder.",
                          path=outside[0])
    return root


def read_upload(filename: str, data: bytes) -> UploadedSkill:
    if len(data) > MAX_UPLOAD_BYTES:
        raise BundleError("skill_upload_too_large", "Uploads are at most 5 MB.")
    if data.startswith(_ZIP_MAGIC) or filename.lower().endswith(".zip"):
        entries = _zip_files(data)
        root = _skill_root([path for path, _, _ in entries])
        files = [BundleFile(path[len(root):], decode_text(path, content), executable)
                 for path, content, executable in entries]
        folder = root.rstrip("/") or None
    else:
        files = [BundleFile(SKILL_FILE, decode_text(filename or SKILL_FILE, data))]
        folder = None
    files = check_limits(files)
    if folder is None:
        try:
            name = parse_skill_md(next(item.content for item in files if item.path == SKILL_FILE)).frontmatter.get(
                "name")
        except SkillSpecError:
            name = None
        folder = str(name) if name else None
    return UploadedSkill(folder=folder, files=files)


__all__ = ["MAX_RATIO", "MAX_UPLOAD_BYTES", "UploadedSkill", "read_upload"]
