"""Extracting a corporate identity profile from an uploaded template, and its AI-ready template."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .guide import build_identity_summary as _build_identity_summary
from .guide import generate_llm_guide as _generate_llm_guide
from .icons import extract_icon_catalog as _extract_icon_catalog
from .layouts import extract_layout_catalog as _extract_layout_catalog
from .layouts import extract_slide_dimensions as _extract_slide_dimensions
from .layouts import extract_theme as _extract_theme
from .parsing import utc_now_iso as _utc_now_iso
from .parsing import write_json as _write_json


def _extract_corp_identity_profile(
    source_path: Path, profile_root: Path, *, profile_id: str, profile_name: str
) -> dict[str, Any]:
    extracted_root = profile_root / "_extracted"
    if extracted_root.exists():
        shutil.rmtree(extracted_root)
    extracted_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_path) as archive:
        archive.extractall(extracted_root)

    brand = _extract_theme(extracted_root)
    slide_dimensions = _extract_slide_dimensions(extracted_root)
    layout_catalog = _extract_layout_catalog(extracted_root, brand, slide_dimensions)
    icon_catalog = _extract_icon_catalog(extracted_root, profile_root)
    summary = _build_identity_summary(
        profile_id=profile_id,
        name=profile_name,
        source_file_name=source_path.name,
        brand=brand,
        layout_catalog=layout_catalog,
        icon_catalog=icon_catalog,
        profile_root=profile_root,
    )
    guide = _generate_llm_guide(summary, layout_catalog, icon_catalog)
    brand_profile = {
        "profile_id": profile_id,
        "name": profile_name,
        "source_file_name": source_path.name,
        "created_at": _utc_now_iso(),
        "summary": summary,
        "brand": brand,
        "layout_catalog": {
            "summary": layout_catalog.get("summary") or {},
        },
        "icon_catalog": {
            "total_icons": icon_catalog.get("total_icons") or 0,
            "categories": {
                category: {
                    "count": len(items),
                    "examples": [item.get("slug") for item in items[:5]],
                }
                for category, items in (icon_catalog.get("categories") or {}).items()
            },
        },
    }
    _write_json(profile_root / "brand-profile.json", brand_profile)
    _write_json(profile_root / "layout-catalog.json", layout_catalog)
    _write_json(profile_root / "icon-catalog.json", icon_catalog)
    (profile_root / "llm-guide.md").write_text(guide, encoding="utf-8")
    return {
        "summary": summary,
        "brand_profile_path": str((profile_root / "brand-profile.json").resolve()),
        "layout_catalog_path": str((profile_root / "layout-catalog.json").resolve()),
        "icon_catalog_path": str((profile_root / "icon-catalog.json").resolve()),
        "guide_path": str((profile_root / "llm-guide.md").resolve()),
        "guide_markdown": guide,
    }


def _build_ai_ready_corp_identity_template(source_path: Path, profile_root: Path) -> dict[str, str]:
    from ..lean_template_builder import build_lean_ai_template

    ai_root = (profile_root / "ai-template").resolve()
    ai_root.mkdir(parents=True, exist_ok=True)

    stem = source_path.stem
    output_pptx = ai_root / f"{stem}-ai.pptx"
    output_potx = ai_root / f"{stem}-ai.potx"

    result = build_lean_ai_template(source_path, output_pptx, output_potx)
    ai_template_path = str(output_potx)

    # Persist the example slide map alongside the template
    example_map_path = ai_root / "example-slide-map.json"
    example_map_path.write_text(
        json.dumps(result.get("example_slide_map", {}), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return {
        "ai_template_path": ai_template_path,
        "ai_pptx_path": str(output_pptx),
        "example_slide_map_path": str(example_map_path),
        "slide_count": result.get("slide_count", 0),
        "layout_count": result.get("layout_count", 0),
        "media_count": result.get("media_count", 0),
        "size_mb": result.get("size_mb", 0),
    }
