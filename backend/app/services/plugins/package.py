"""A plugin package read into memory and checked: the manifest and every file it points at (no database)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..skill_catalog.bundle import MAX_BUNDLE_BYTES, MAX_BUNDLE_FILES, MAX_FILE_BYTES, BundleError, normalize_path
from .manifest import MANIFEST_FILE, Manifest, ManifestError, issue
from .manifest_parse import parse_manifest
from .package_content import RoleContent, SkillContent, WorkflowContent, _document, _role, _skill, _workflow

SKIPPED = ("__MACOSX/", ".git/")
SKIPPED_NAMES = (".DS_Store",)


@dataclass(slots=True)
class PluginPackage:
    manifest: Manifest
    digest: str
    files: dict[str, bytes]
    skills: list[SkillContent] = field(default_factory=list)
    workflows: list[WorkflowContent] = field(default_factory=list)
    roles: list[RoleContent] = field(default_factory=list)
    settings_schema: dict[str, Any] | None = None


class PackageError(Exception):
    def __init__(self, issues: list[dict[str, str]]) -> None:
        super().__init__("; ".join(item["message"] for item in issues))
        self.issues = issues


def package_digest(files: dict[str, bytes]) -> str:
    lines = "\n".join(f"{path}\0{hashlib.sha256(data).hexdigest()}" for path, data in sorted(files.items()))
    return "sha256:" + hashlib.sha256(lines.encode()).hexdigest()


def _rooted(files: dict[str, bytes]) -> dict[str, bytes]:
    if MANIFEST_FILE in files:
        return files
    roots = {path.split("/", 1)[0] for path in files if path.endswith("/" + MANIFEST_FILE)
             and path.count("/") == 1}
    if len(roots) != 1:
        raise PackageError([issue("package_manifest_missing",
                                  f"The package has no {MANIFEST_FILE} at its root or in one top-level folder.")])
    root = roots.pop() + "/"
    return {path[len(root):]: data for path, data in files.items() if path.startswith(root)}


def _checked(entries: list[tuple[str, bytes]]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    for raw_path, data in entries:
        try:
            path = normalize_path(raw_path)
        except BundleError as error:
            raise PackageError([issue(error.code, error.message, str(error.details.get("path") or ""))]) from None
        if path.startswith(SKIPPED) or path.rsplit("/", 1)[-1] in SKIPPED_NAMES:
            continue
        if len(data) > MAX_FILE_BYTES:
            raise PackageError([issue("package_file_too_large", "A file is larger than 1 MB.", path)])
        total += len(data)
        files[path] = data
    if total > MAX_BUNDLE_BYTES:
        raise PackageError([issue("package_too_large", "A plugin package is at most 5 MB.")])
    if len(files) > MAX_BUNDLE_FILES:
        raise PackageError([issue("package_too_many_files", f"A plugin package has at most {MAX_BUNDLE_FILES} files.")])
    return _rooted(files)


def files_from_zip(data: bytes) -> dict[str, bytes]:
    from ..skill_catalog.archive import _zip_files

    try:
        return _checked([(path, content) for path, content, _ in _zip_files(data)])
    except BundleError as error:
        raise PackageError([issue(error.code, error.message, str(error.details.get("path") or ""))]) from None


def files_from_folder(folder: Path) -> dict[str, bytes]:
    entries = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise PackageError([issue("package_symlink", "Symbolic links are not allowed.",
                                      str(path.relative_to(folder)))])
        if path.is_file():
            entries.append((path.relative_to(folder).as_posix(), path.read_bytes()))
    return _checked(entries)



def read_package(files: dict[str, bytes]) -> PluginPackage:
    text = files.get(MANIFEST_FILE)
    try:
        manifest = parse_manifest((text or b"").decode("utf-8", errors="replace"))
    except ManifestError as error:
        raise PackageError(error.issues) from None
    issues: list[dict[str, str]] = []
    package = PluginPackage(manifest=manifest, digest=package_digest(files), files=files)
    package.skills = [item for item in (_skill(files, path, issues) for path in manifest.skills) if item]
    package.workflows = [item for item in (_workflow(files, path, manifest, issues) for path in manifest.workflows)
                         if item]
    package.roles = [item for item in (_role(files, path, issues) for path in manifest.roles) if item]
    for kind, items in (("skill", [s.name for s in package.skills]), ("workflow", [w.key for w in package.workflows]),
                        ("role", [r.key for r in package.roles])):
        for name in {item for item in items if items.count(item) > 1}:
            issues.append(issue("package_duplicate", f"Two {kind}s are named '{name}'."))
    if manifest.settings:
        schema = _document(files, manifest.settings, issues)
        if schema is not None and schema.get("type") != "object":
            issues.append(issue("settings_schema_invalid", "The settings schema is a JSON schema of type object.",
                                manifest.settings))
        package.settings_schema = schema
    if manifest.ui and manifest.ui.get("bundle"):
        bundle = manifest.ui["bundle"] + "/"
        for slot in ("pages", "tiles", "tabs", "phone"):
            for entry in manifest.ui.get(slot) or []:
                if bundle + entry["entry"] not in files:
                    issues.append(issue("ui_entry_missing", f"{bundle}{entry['entry']} is not in the package.",
                                        f"contributes.ui.{slot}"))
    if issues:
        raise PackageError(issues)
    return package


__all__ = ["PackageError", "PluginPackage", "files_from_folder", "files_from_zip", "package_digest", "read_package"]
