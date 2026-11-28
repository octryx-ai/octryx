"""Registry fields derived from an uploaded template: extraction, AI-ready template, normalisation, office theme."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .normalized_template import build_profile_normalization
from .normalized_template_resolve import normalization_record_fields


def _normalization_fields(source_path: Path, profile_root: Path) -> dict[str, Any]:
    result = build_profile_normalization(source_path, profile_root)
    return normalization_record_fields(profile_root, result)


def _extraction_fields(extraction: dict[str, Any], ai_ready: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": extraction["summary"],
        "brand_profile_path": extraction["brand_profile_path"],
        "layout_catalog_path": extraction["layout_catalog_path"],
        "icon_catalog_path": extraction["icon_catalog_path"],
        "guide_path": extraction["guide_path"],
        "ai_template_path": ai_ready["ai_template_path"],
        "ai_pptx_path": ai_ready.get("ai_pptx_path", ""),
        "example_slide_map_path": ai_ready.get("example_slide_map_path", ""),
        "ai_slide_count": ai_ready.get("slide_count", 0),
        "ai_layout_count": ai_ready.get("layout_count", 0),
        "ai_size_mb": ai_ready.get("size_mb", 0),
    }


def _extract_office_template(
    *,
    profile_root: Path,
    source_path: Path,
    profile_id: str,
    profile_name: str,
    safe_name: str,
    doc_type: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    import zipfile

    from .office_doc_parsing import (
        extract_office_document_summary,
        extract_office_document_theme,
        generate_office_document_guide,
    )

    extracted_root = profile_root / "_extracted"
    if extracted_root.exists():
        shutil.rmtree(extracted_root)
    extracted_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_path) as archive:
        archive.extractall(extracted_root)

    brand = extract_office_document_theme(extracted_root)
    summary = extract_office_document_summary(
        profile_id=profile_id,
        name=profile_name,
        source_file_name=safe_name,
        brand=brand,
        doc_type=doc_type,
        profile_root=profile_root,
    )
    guide = generate_office_document_guide(summary, doc_type)
    return brand, summary, guide
