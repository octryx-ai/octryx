"""Storage lifecycle helpers for corporate identity profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .normalized_template_manifest import (
    NORMALIZATION_MANIFEST_NAME,
    NORMALIZED_TEMPLATE_NAME,
    TEMPLATE_SNAPSHOT_NAME,
    read_normalization_manifest,
)

GENERATED_PROFILE_FILENAMES: tuple[str, ...] = (
    "brand-profile.json",
    "layout-catalog.json",
    "icon-catalog.json",
    "llm-guide.md",
    NORMALIZATION_MANIFEST_NAME,
    TEMPLATE_SNAPSHOT_NAME,
)

PRESENTATION_SOURCE_SUFFIXES = {".potx", ".pptx"}
OFFICE_COMPANION_SUFFIXES = {".dotx", ".docx", ".xltx", ".xlsx"}


def _path_entry(path: Path, *, kind: str) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "kind": kind,
        "exists": path.exists(),
    }


def _unique_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        path = str(entry.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        deduped.append(entry)
    return deduped


_COMPANION_TEMPLATE_FIELDS: tuple[str, ...] = (
    "docx_template_path",
    "word_template_path",
    "xlsx_template_path",
    "excel_template_path",
    "ai_docx_template_path",
    "ai_xlsx_template_path",
)


def _source_entries(source_path: Path, source_dir: Path) -> list[dict[str, Any]]:
    source_of_truth: list[dict[str, Any]] = []
    if source_path:
        source_of_truth.append(_path_entry(source_path, kind="source_upload"))
    if source_dir.exists():
        source_of_truth.append(_path_entry(source_dir, kind="source_directory"))
    return source_of_truth


def _sort_normalized_template(
    profile_root: Path, rebuildable: list[dict[str, Any]], retained_companions: list[dict[str, Any]]
) -> None:
    normalized_template = profile_root / NORMALIZED_TEMPLATE_NAME
    if normalized_template.exists():
        # A derivative we generated is reproducible from the original. One the
        # customer edited is their work: it moves out of the cleanup set and is
        # retained like any companion template.
        if bool(read_normalization_manifest(profile_root).get("customized")):
            retained_companions.append(_path_entry(normalized_template, kind="customized_template"))
        else:
            rebuildable.append(_path_entry(normalized_template, kind="generated_template"))


def _ai_template_entries(source_path: Path, ai_template_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    source_stem = source_path.stem.strip()
    if source_stem:
        entries.append(_path_entry(ai_template_dir / f"{source_stem}-ai.pptx", kind="generated_ai_template"))
        entries.append(_path_entry(ai_template_dir / f"{source_stem}-ai.potx", kind="generated_ai_template"))
    entries.append(_path_entry(ai_template_dir / "example-slide-map.json", kind="generated_ai_metadata"))
    return entries


def _companion_entries(profile: dict[str, Any], ai_template_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for field_name in _COMPANION_TEMPLATE_FIELDS:
        raw_value = str(profile.get(field_name) or "").strip()
        if not raw_value:
            continue
        candidate = Path(raw_value).expanduser()
        entries.append(_path_entry(candidate, kind="office_companion"))

    if ai_template_dir.exists():
        for candidate in sorted(ai_template_dir.iterdir()):
            if candidate.suffix.lower() not in OFFICE_COMPANION_SUFFIXES:
                continue
            entries.append(_path_entry(candidate, kind="office_companion"))
    return entries


def describe_profile_storage_lifecycle(profile: dict[str, Any]) -> dict[str, Any]:
    profile_root = Path(str(profile.get("profile_root") or "")).expanduser()
    source_path = Path(str(profile.get("source_path") or "")).expanduser()
    source_dir = profile_root / "source"
    extracted_dir = profile_root / "_extracted"
    ai_template_dir = profile_root / "ai-template"
    source_suffix = source_path.suffix.lower()

    source_of_truth = _source_entries(source_path, source_dir)
    rebuildable: list[dict[str, Any]] = []
    retained_companions: list[dict[str, Any]] = []

    rebuildable.append(_path_entry(extracted_dir, kind="extracted_cache"))
    for filename in GENERATED_PROFILE_FILENAMES:
        rebuildable.append(_path_entry(profile_root / filename, kind="generated_metadata"))

    _sort_normalized_template(profile_root, rebuildable, retained_companions)

    if source_suffix in PRESENTATION_SOURCE_SUFFIXES:
        rebuildable.extend(_ai_template_entries(source_path, ai_template_dir))

    retained_companions.extend(_companion_entries(profile, ai_template_dir))

    source_of_truth = _unique_entries(source_of_truth)
    rebuildable = _unique_entries(rebuildable)
    retained_companions = _unique_entries(retained_companions)

    return {
        "profile_root": str(profile_root.resolve()),
        "source_of_truth": source_of_truth,
        "rebuildable": rebuildable,
        "retained_companions": retained_companions,
        "safe_cleanup_paths": [entry["path"] for entry in rebuildable],
        "reextract_supported": source_suffix in PRESENTATION_SOURCE_SUFFIXES and source_path.exists(),
        "cleanup_note": (
            "Only rebuildable paths are safe cleanup targets. "
            "Source uploads and companion Office templates are retained."
        ),
    }
