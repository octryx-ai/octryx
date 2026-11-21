"""Helpers for configurable Office template libraries."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

OFFICE_TEMPLATE_DOC_TYPES = {"docx", "xlsx", "pptx"}
OFFICE_TEMPLATE_BUILTIN_ROOT = Path(__file__).resolve().parents[3] / ".octryx" / "template"
OFFICE_TEMPLATE_EXTENSIONS: dict[str, str] = {
    ".docx": "docx",
    ".dotx": "docx",
    ".xlsx": "xlsx",
    ".xltx": "xlsx",
    ".pptx": "pptx",
    ".potx": "pptx",
}
OFFICE_TEMPLATE_ENTRY_OPTIONAL_PATH_FIELDS = (
    "source_path",
    "ai_template_path",
    "package_manifest_path",
)
OFFICE_TEMPLATE_STORAGE_CONTRACT_FIELDS = (
    "doc_type",
    "storage_kind",
    "source_path",
    "active_template_path",
    "package_root",
    "package_manifest_path",
    "generated_artifact_root",
    "ai_template_path",
    "has_import_package",
    "has_generated_ai_artifact",
)


def office_template_doc_type_for_path(path: str | Path) -> str:
    return OFFICE_TEMPLATE_EXTENSIONS.get(Path(path).suffix.lower(), "")


def sanitize_office_template_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or "office-template"


def _normalize_office_template_storage_contract(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    normalized: dict[str, Any] = {}
    for key in OFFICE_TEMPLATE_STORAGE_CONTRACT_FIELDS:
        value = raw.get(key)
        if isinstance(value, bool):
            normalized[key] = value
            continue
        text = str(value or "").strip()
        if text:
            normalized[key] = text
    return normalized or None


def normalize_office_template_library(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    defaults_by_type: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        doc_type = str(item.get("doc_type") or office_template_doc_type_for_path(path)).strip().lower()
        if not path or doc_type not in OFFICE_TEMPLATE_DOC_TYPES:
            continue
        key = sanitize_office_template_key(str(item.get("key") or Path(path).stem))
        if key in seen_keys:
            suffix = 2
            while f"{key}-{suffix}" in seen_keys:
                suffix += 1
            key = f"{key}-{suffix}"
        seen_keys.add(key)
        is_default = bool(item.get("is_default"))
        if is_default:
            if doc_type in defaults_by_type:
                is_default = False
            else:
                defaults_by_type.add(doc_type)
        normalized_item = {
            "key": key,
            "name": str(item.get("name") or Path(path).stem.replace("-", " ").replace("_", " ").title()).strip()
            or Path(path).name,
            "doc_type": doc_type,
            "path": path,
            "description": str(item.get("description") or "").strip(),
            "is_default": is_default,
        }
        for field in OFFICE_TEMPLATE_ENTRY_OPTIONAL_PATH_FIELDS:
            value = str(item.get(field) or "").strip()
            if value:
                normalized_item[field] = value
        storage_contract = _normalize_office_template_storage_contract(item.get("storage_contract"))
        if storage_contract is not None:
            normalized_item["storage_contract"] = storage_contract
        normalized.append(normalized_item)
    return normalized


def built_in_office_template_library() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not OFFICE_TEMPLATE_BUILTIN_ROOT.exists():
        return entries
    preferred_dirs = sorted(
        [path for path in OFFICE_TEMPLATE_BUILTIN_ROOT.iterdir() if path.is_dir() and path.name.endswith("-ai")]
    )
    for directory in preferred_dirs:
        template_candidates = (
            sorted(directory.glob("*.potx")) + sorted(directory.glob("*.dotx")) + sorted(directory.glob("*.xltx"))
        )
        for template_path in template_candidates:
            doc_type = office_template_doc_type_for_path(template_path)
            if doc_type not in OFFICE_TEMPLATE_DOC_TYPES:
                continue
            key = f"{directory.name}-{doc_type}"
            entries.append(
                {
                    "key": key,
                    "name": template_path.stem.replace("-", " ").replace("_", " ").title(),
                    "doc_type": doc_type,
                    "path": str(template_path.resolve()),
                    "description": f"Built-in AI-ready {doc_type.upper()} template from {directory.name}.",
                    "is_default": True,
                }
            )
    return normalize_office_template_library(entries)


def merge_office_template_libraries(*libraries: Any) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    by_key: dict[str, int] = {}
    for raw in libraries:
        for item in normalize_office_template_library(raw):
            key = str(item.get("key") or "")
            if key in by_key:
                ordered[by_key[key]] = item
            else:
                by_key[key] = len(ordered)
                ordered.append(item)
    normalized = normalize_office_template_library(ordered)
    defaults_by_type = {
        str(item.get("doc_type") or "").strip().lower() for item in normalized if bool(item.get("is_default"))
    }
    if defaults_by_type >= OFFICE_TEMPLATE_DOC_TYPES:
        return normalized
    builtins = built_in_office_template_library()
    fallback_by_type = {
        str(item.get("doc_type") or "").strip().lower(): item for item in builtins if bool(item.get("is_default"))
    }
    for doc_type, item in fallback_by_type.items():
        if doc_type not in defaults_by_type:
            normalized.append(item)
    return normalize_office_template_library(normalized)


def suggest_office_template_entry(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    doc_type = office_template_doc_type_for_path(resolved)
    if doc_type not in OFFICE_TEMPLATE_DOC_TYPES:
        raise ValueError(f"unsupported office template file type: {resolved.suffix}")
    return {
        "key": sanitize_office_template_key(resolved.stem),
        "name": resolved.stem.replace("-", " ").replace("_", " ").title() or resolved.name,
        "doc_type": doc_type,
        "path": str(resolved),
        "description": "",
        "is_default": False,
    }


def resolve_office_template_entry(
    library: list[dict[str, Any]],
    *,
    template_key: str = "",
    doc_type: str = "",
) -> dict[str, Any] | None:
    normalized_key = sanitize_office_template_key(template_key) if template_key else ""
    normalized_doc_type = str(doc_type or "").strip().lower()
    if normalized_key:
        for item in library:
            if str(item.get("key") or "").strip().lower() == normalized_key:
                return item
    if normalized_doc_type in OFFICE_TEMPLATE_DOC_TYPES:
        for item in library:
            if str(item.get("doc_type") or "").strip().lower() == normalized_doc_type and bool(item.get("is_default")):
                return item
    return None
