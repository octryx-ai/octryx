"""Template entries of a corporate identity profile, rebuilt from the profile and its source folder."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .templates import CORP_IDENTITY_TEMPLATE_SUFFIXES


def _stable_template_id(doc_type: str, source_file_name: str) -> str:
    digest = hashlib.md5(f"{doc_type}:{source_file_name}".encode(), usedforsecurity=False)
    return digest.hexdigest()


def _template_meta_for(profile: dict[str, Any], source_file_name: str) -> dict[str, Any]:
    store = profile.get("template_meta")
    if isinstance(store, dict):
        entry = store.get(source_file_name)
        if isinstance(entry, dict):
            return entry
    return {}


def _template_entry(
    profile: dict[str, Any], doc_type: str, source_path: str, default_name: str
) -> dict[str, Any]:
    source_file_name = Path(source_path).name
    meta = _template_meta_for(profile, source_file_name)
    return {
        "template_id": _stable_template_id(doc_type, source_file_name),
        "type": doc_type,
        "source_path": source_path,
        "display_name": str(meta.get("display_name") or "").strip() or default_name,
        "description": str(meta.get("description") or "").strip(),
        "source_file_name": source_file_name,
        "created_at": profile.get("created_at"),
    }


def _build_template_entry(
    profile: dict[str, Any],
    doc_type: str,
    profile_root: Path,
    summary: dict[str, Any],
) -> dict[str, Any] | None:
    path_key_map = {
        "pptx": ["ai_template_path", "source_path"],
        "docx": ["docx_template_path", "ai_docx_template_path", "word_template_path"],
        "xlsx": ["xlsx_template_path", "ai_xlsx_template_path", "excel_template_path"],
    }
    source_path = ""
    for key in path_key_map.get(doc_type, []):
        raw = str(profile.get(key) or "").strip()
        if raw:
            candidate = Path(raw).expanduser()
            if candidate.exists():
                source_path = str(candidate.resolve())
                break

    if not source_path:
        return None
    return _template_entry(profile, doc_type, source_path, summary.get("name") or Path(source_path).stem)


def _build_template_map(profile: dict[str, Any], profile_root: Path) -> dict[str, list[dict[str, Any]]]:
    summary = dict(profile.get("summary") or {})
    templates: dict[str, list[dict[str, Any]]] = {"pptx": [], "docx": [], "xlsx": []}
    for doc_type in ("pptx", "docx", "xlsx"):
        seen_files: set[str] = set()
        # Check explicit field first
        entry = _build_template_entry(profile, doc_type, profile_root, summary)
        if entry:
            templates[doc_type].append(entry)
            seen_files.add(str(entry.get("source_file_name") or ""))
        # Then scan source/ directory, skipping files already surfaced above so
        # the same template does not appear twice with two ids.
        source_dir = profile_root / "source"
        if source_dir.exists():
            suffixes = CORP_IDENTITY_TEMPLATE_SUFFIXES.get(doc_type, ())
            for candidate in sorted(source_dir.iterdir()):
                if candidate.suffix.lower() in suffixes and candidate.name not in seen_files:
                    seen_files.add(candidate.name)
                    default_name = candidate.stem.replace("-", " ").replace("_", " ").strip()
                    templates[doc_type].append(
                        _template_entry(profile, doc_type, str(candidate.resolve()), default_name)
                    )
    return templates
