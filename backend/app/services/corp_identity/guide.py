"""Guide and summary generation for corporate identity profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .guide_examples import build_worked_example
from .guide_layouts import layout_choice_lines
from .guide_sections import (
    SHAPE_TARGETING_TIPS,
    brand_section,
    core_rules_section,
    icon_reference_lines,
    icons_section,
    layout_detail_lines,
    layout_selection_lines,
)


def build_identity_summary(
    *,
    profile_id: str,
    name: str,
    source_file_name: str,
    brand: dict[str, Any],
    layout_catalog: dict[str, Any],
    icon_catalog: dict[str, Any],
    profile_root: Path,
) -> dict[str, Any]:
    colors = brand.get("color_scheme") or {}
    color_list = [
        {
            "token": token,
            "hex": info.get("hex"),
            "name": info.get("name"),
        }
        for token, info in list(colors.items())[:8]
    ]
    layouts = layout_catalog.get("layouts") or []
    safe_layouts = [item for item in layouts if item.get("corporate_safe")]
    icon_categories = [
        {
            "name": category,
            "count": len(items),
            "examples": [item.get("slug") for item in items[:4]],
        }
        for category, items in sorted((icon_catalog.get("categories") or {}).items())
    ]
    return {
        "id": profile_id,
        "name": name,
        "source_file_name": source_file_name,
        "theme_name": brand.get("theme_name") or "",
        "font_family": brand.get("font_family") or "",
        "colors": color_list,
        "layout_count": len(layouts),
        "corporate_safe_layout_count": len(safe_layouts),
        "recommended_layouts": [item.get("name") for item in safe_layouts[:10]],
        "icon_count": int(icon_catalog.get("total_icons") or 0),
        "icon_categories": icon_categories,
        "profile_root": str(profile_root),
    }


def generate_llm_guide(
    summary: dict[str, Any],
    layout_catalog: dict[str, Any],
    icon_catalog: dict[str, Any],
    lean_slide_map: dict[str, int] | None = None,
) -> str:
    profile_name = summary.get("name") or "Profile"
    profile_root = str(summary.get("profile_root") or "")
    layouts: list[dict[str, Any]] = layout_catalog.get("layouts") or []
    safe_layouts = [layout for layout in layouts if layout.get("corporate_safe")]
    icon_categories_data: dict[str, list[dict[str, Any]]] = icon_catalog.get("categories") or {}

    selection_lines = layout_selection_lines(layout_catalog, layouts)
    detail_lines = layout_detail_lines(safe_layouts, lean_slide_map)
    icon_ref_lines = icon_reference_lines(icon_categories_data)
    ex_lines, tmpl_count = build_worked_example(
        layouts=layouts,
        safe_layouts=safe_layouts,
        icon_categories_data=icon_categories_data,
        profile_root=profile_root,
        lean_slide_map=lean_slide_map,
        sample_slides=int((layout_catalog.get("summary") or {}).get("sample_slide_count") or 0),
    )

    sections: list[str] = []
    sections.extend(core_rules_section(profile_name, tmpl_count))
    sections.extend(
        brand_section(summary, profile_name=profile_name, profile_root=profile_root, layout_catalog=layout_catalog)
    )
    sections.append("## Layout Selection Guide")
    sections.extend(selection_lines or ["- No layouts detected."])
    sections.extend(layout_choice_lines(safe_layouts))
    sections.append("## Full Layout Reference (corporate-safe only)")
    sections.extend(detail_lines or ["- No layouts extracted."])
    sections.extend(icons_section(profile_root, icon_ref_lines))
    sections.append("## Worked Example: 5-Slide Deck")
    sections.extend(ex_lines)
    sections.append("")
    sections.extend(SHAPE_TARGETING_TIPS)
    return "\n".join(sections).strip() + "\n"
