"""Section builders for the corporate identity LLM guide.

Each helper returns the lines of one guide section; ``generate_llm_guide`` joins them in order.
"""

from __future__ import annotations

from typing import Any

from .layout_structure import layout_hint

CATEGORY_PURPOSE: dict[str, str] = {
    "title": "Opening slide. Use exactly once at the start.",
    "section": "Chapter divider between major sections.",
    "content": "Text, bullets, comparisons, tables. Main workhorse.",
    "icons": "3–4 visual topics, each with SVG icon + heading + body text.",
    "statement": "Big bold quote or key message. Minimal text.",
    "picture": "Full or half-screen image. Visual impact slide.",
    "blank": "Custom freeform. Place shapes and icons freely.",
    "contact": "Presenter / team contact details. Usually the last slide.",
}

SHAPE_TARGETING_TIPS: list[str] = [
    "## Shape Targeting Tips",
    '- After cloning with `from_path`, ALWAYS call `get_office_element(path="/slide[N]")` to see shape indices.',
    "- Shape indices depend on the cloned slide — they are NOT always 1=title, 2=body.",
    "- Look at the `type` and `text` preview in the get response to identify which shape to set.",
    "- For icon layouts: find shapes by inspecting get response, not by guessing index.",
    "- After `add_office_element`, the new slide is always the **last** slide in the deck.",
    "  Use `get_office_document_info` to get total slide count, then target `/slide[count]`.",
]

_CLONE_USAGE: list[str] = [
    "**For layouts WITH an example slide** (preferred):",
    "```",
    'add_office_element(file_path, parent_path="/", element_type="slide",',
    '                   from_path="/slide[EXAMPLE_N]")  # clone example slide',
    'get_office_element(file_path, path="/slide[NEW_N]")  # ALWAYS inspect first',
    "# Find the shape with type=title in the result — its index varies per layout",
    "# (a cover may list the title first, a content layout may list the slide number first)",
    'set_office_property(file_path, path="/slide[NEW_N]/shape[TITLE_IDX]", properties={"text": "Title"})',
    "# If a body shape is present, set it; otherwise add one at the layout's placeholder position:",
    '# add_office_element(file_path, parent_path="/slide[NEW_N]", element_type="shape",',
    '#                    properties={"text": "Body", "x": "1.27cm", "y": "3.14cm",',
    '#                               "width": "22.88cm", "height": "9.9cm"})',
    "```",
    "",
    "**For layouts WITHOUT an example slide** (fallback):",
    "```",
    'add_office_element(file_path, parent_path="/", element_type="slide",',
    '                   properties={"layout": "<exact name>"})  # title-only',
    'set_office_property(file_path, path="/slide[N]/shape[1]", properties={"text": "Title"})',
    "# Body text: add a shape at the layout's body placeholder position:",
    'add_office_element(file_path, parent_path="/slide[N]", element_type="shape",',
    '                   properties={"text": "Body", "x": "1.27cm", "y": "3.14cm",',
    '                               "width": "22.9cm", "height": "9.9cm"})',
    "```",
    "",
]

_OTHER_RULES: list[str] = [
    "### Other rules",
    "- Use `get_office_element` on the new slide to inspect shape indices before setting text.",
    "- Vary layouts across slides — avoid repeating the same layout more than twice in a row.",
    "- For 3–4 visual topics use one of the template's icon topic layouts (see the table) and add SVG icons"
    " into its icon zones.",
    "- Use a statement or quote layout for bold key messages instead of a plain bullet slide.",
    "- Never guess layout names — use only names from the list below.",
    "- Prefer corporate-safe layouts. Avoid photo-placeholder layouts unless the user explicitly asks.",
    "",
]


def layout_selection_lines(layout_catalog: dict[str, Any], layouts: list[dict[str, Any]]) -> list[str]:
    """List corporate-safe layout names grouped by category with each category's purpose."""
    by_cat = (layout_catalog.get("summary") or {}).get("by_category") or {}
    selection_lines = []
    for cat in sorted(by_cat):
        names = by_cat[cat]
        safe_names = [
            name
            for name in names
            if any(layout.get("name") == name and layout.get("corporate_safe") for layout in layouts)
        ]
        if not safe_names:
            continue
        selection_lines.append(f"**{cat.upper()}** — {CATEGORY_PURPOSE.get(cat, '')}")
        for name in safe_names:
            selection_lines.append(f"  - `{name}`")
        selection_lines.append("")
    return selection_lines


def _placeholder_rows(phs: list[dict[str, Any]]) -> list[str]:
    ph_rows = []
    for ph in phs:
        ph_type = ph.get("placeholder_type") or ""
        if ph_type in ("sldNum", "ftr", "dt"):
            continue
        purpose = ph.get("purpose") or ph_type
        tg = ph.get("text_guideline") or {}
        max_chars = tg.get("max_chars", "")
        hint_text = tg.get("hint", "")
        x = ph.get("x_cm")
        y = ph.get("y_cm")
        pos = f"{x:.1f},{y:.1f}cm" if x is not None and y is not None else "inherited"
        ph_rows.append(
            f"  - `{ph_type}[{ph.get('placeholder_index', 0)}]` — {purpose} | pos={pos}"
            f" | max {max_chars} chars | {hint_text}"
        )
    return ph_rows


def _icon_zone_lines(zones: list[dict[str, Any]]) -> list[str]:
    lines = ["  Icon zones:"]
    for zone in zones:
        lines.append(
            f"    - x={zone.get('x_cm', 0):.2f}cm y={zone.get('y_cm', 0):.2f}cm "
            f"w={zone.get('w_cm', 2.5):.2f}cm h={zone.get('h_cm', 2.5):.2f}cm — {zone.get('note', '')}"
        )
    return lines


def layout_detail_lines(safe_layouts: list[dict[str, Any]], lean_slide_map: dict[str, int] | None) -> list[str]:
    """Describe each corporate-safe layout: hint, how to clone it, placeholders and icon zones."""
    lines: list[str] = []
    for layout in safe_layouts:
        lname = layout.get("name") or ""
        hint = layout_hint(layout)
        phs = layout.get("placeholders") or []
        zones = layout.get("icon_zones") or []
        ex_slide = (lean_slide_map or {}).get(lname) or layout.get("example_slide_index")
        clone_cmd = (
            f'clone: `from_path="/slide[{ex_slide}]"`'
            if ex_slide
            else f'no example — use `properties={{"layout": "{lname}"}}`'
        )
        lines.append(f"### `{lname}`")
        lines.append(f"*{hint}* | {clone_cmd}")
        lines.append("")
        lines.extend(_placeholder_rows(phs) or ["  - *No editable placeholders (freeform canvas)*"])
        if zones:
            lines.extend(_icon_zone_lines(zones))
        lines.append("")
    return lines


def icon_reference_lines(icon_categories_data: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Summarise each icon category with its folder and a few example slugs."""
    icon_ref_lines = []
    for cat_name in sorted(icon_categories_data):
        items = icon_categories_data[cat_name]
        examples = [item.get("slug") or "" for item in items[:6] if item.get("slug")]
        cat_dir = items[0].get("named_path", "").split("/")[0] if items else ""
        icon_ref_lines.append(f"**{cat_name}** ({len(items)} icons, folder `{cat_dir}/`):")
        icon_ref_lines.append(f"  examples: {', '.join(examples)}")
    return icon_ref_lines


def core_rules_section(profile_name: str, tmpl_count: int) -> list[str]:
    """Return the guide heading and the core rules on adding and cleaning up slides."""
    return [
        f"# Corporate Identity Guide: {profile_name}",
        "",
        "## Core Rules",
        "",
        "### CRITICAL: How to add slides",
        f"After `create_office_document`, the file contains **{tmpl_count} template example slides**"
        f" (slides 1–{tmpl_count}).",
        f"Your content slides are appended AFTER them: first content slide = `/slide[{tmpl_count + 1}]`,"
        f" second = `/slide[{tmpl_count + 2}]`, etc.",
        f"**At the end, always remove the {tmpl_count} template slides** by calling"
        f' `remove_office_element(path="/slide[1]")` {tmpl_count} times.',
        "",
        "This template uses **floating shapes** (not standard OOXML placeholders) for body content.",
        'Adding a slide via `properties={"layout": ...}` only creates the title shape; all body shapes are missing.',
        "**ALWAYS use `from_path` to clone a template example slide**"
        " — this preserves all floating shapes at correct positions.",
        "",
        *_CLONE_USAGE,
        *_OTHER_RULES,
    ]


def brand_section(
    summary: dict[str, Any],
    *,
    profile_name: str,
    profile_root: str,
    layout_catalog: dict[str, Any],
) -> list[str]:
    """Return the brand facts and the colour palette table."""
    theme_name = summary.get("theme_name") or "-"
    font_family = summary.get("font_family") or "Arial"
    dims = layout_catalog.get("slide_dimensions") or {}
    slide_w = dims.get("width_cm", 25.4)
    slide_h = dims.get("height_cm", 14.3)
    color_lines = [
        f"| `{c.get('token')}` | `{c.get('hex')}` | {c.get('name')} |" for c in (summary.get("colors") or [])
    ]
    return [
        "## Brand",
        f"- Template: {profile_name} | Theme: {theme_name} | Font: {font_family}",
        f"- Slide size: {slide_w} × {slide_h} cm (16:9 widescreen)",
        f"- {summary.get('layout_count', 0)} layouts total,"
        f" {summary.get('corporate_safe_layout_count', 0)} corporate-safe",
        f"- {summary.get('icon_count', 0)} named SVG icons in `{profile_root}/icons/`",
        "",
        "## Color Palette",
        "| Token | Hex | Name |",
        "|-------|-----|------|",
        *(color_lines or ["| - | - | No palette detected |"]),
        "",
    ]


def icons_section(profile_root: str, icon_ref_lines: list[str]) -> list[str]:
    """Return the available-icons section."""
    return [
        "## Available Icons",
        f"Icons are SVG files under `{profile_root}/icons/<category>/<slug>.svg`.",
        'Always use absolute paths when calling `add_office_element` with `element_type="picture"`.',
        "",
        *(icon_ref_lines or ["- No icons extracted."]),
        "",
    ]
