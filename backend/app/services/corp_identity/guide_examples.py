"""Worked example builders for corporate identity guides."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .guide_layouts import first_layout


def _add_slide(from_path: int | None, layout_name: str) -> list[str]:
    if from_path is not None:
        return [
            'add_office_element(file_path, parent_path="/", element_type="slide",',
            f'                   from_path="/slide[{from_path}]")  # clone "{layout_name}"',
        ]
    return [
        'add_office_element(file_path, parent_path="/", element_type="slide",',
        f'                   properties={{"layout": "{layout_name}"}})  # no example slide — title only',
    ]


def _first_icon_path(icon_categories_data: dict[str, list[dict[str, Any]]], profile_root: str) -> str:
    for _, items in icon_categories_data.items():
        if items:
            return f"{profile_root}/icons/{items[0].get('named_path', '')}"
    return ""


def _create_and_title_steps(tmpl_count: int, ex_title: int | None, title_name: str) -> list[str]:
    s1, s2 = tmpl_count + 1, tmpl_count + 2
    return [
        "```python",
        "# Step 1 – create the deck from the corporate template",
        f"# NOTE: the file starts with {tmpl_count} template example slides (slides 1-{tmpl_count}).",
        f"# Your content slides will be appended AFTER them (slide[{s1}], [{s2}], ...).",
        f"# At the very end, delete the {tmpl_count} template slides — see Step 6.",
        'file_path = "deck.pptx"',
        'create_office_document(file_path=file_path, doc_type="pptx")',
        "",
        "# Step 2 – add title slide (clone example to preserve all layout shapes)",
        *_add_slide(ex_title, title_name),
        f"# New slide is at /slide[{s1}] — always call get_office_element first to find shape indices:",
        f'get_office_element(file_path=file_path, path="/slide[{s1}]")',
        "# Find the type=title and type=subTitle shapes in the result (indices vary per layout):",
        f'set_office_property(file_path=file_path, path="/slide[{s1}]/shape[1]",',
        '                    properties={"text": "My Presentation Title"})',
        f'set_office_property(file_path=file_path, path="/slide[{s1}]/shape[2]",',
        '                    properties={"text": "Subtitle or date"})',
        "",
    ]


def _section_and_content_steps(
    tmpl_count: int, section: tuple[int | None, str], content: tuple[int | None, str]
) -> list[str]:
    s2, s3 = tmpl_count + 2, tmpl_count + 3
    return [
        "# Step 3 – add section divider",
        *_add_slide(*section),
        f'get_office_element(file_path=file_path, path="/slide[{s2}]")',
        "# Find type=title shape and set it:",
        f'set_office_property(file_path=file_path, path="/slide[{s2}]/shape[1]",',
        '                    properties={"text": "Chapter 1"})',
        "",
        "# Step 4 – add content slide with bullets",
        *_add_slide(*content),
        "# Inspect the new slide: find the type=title shape and whether a body shape exists",
        f'get_office_element(file_path=file_path, path="/slide[{s3}]")',
        f'set_office_property(file_path=file_path, path="/slide[{s3}]/shape[2]",',
        '                    properties={"text": "Key Points"})',
        "# If there is no body shape, add a text box at the layout's body position:",
        f'add_office_element(file_path=file_path, parent_path="/slide[{s3}]", element_type="shape",',
        '                   properties={"text": "Point 1\\nPoint 2\\nPoint 3",',
        '                               "x": "1.27cm", "y": "3.14cm",',
        '                               "width": "22.88cm", "height": "9.9cm"})',
        "",
    ]


def _icon_topic_steps(
    tmpl_count: int,
    icons_layout: dict[str, Any] | None,
    ex_icons: int | None,
    icon_path_example: str,
) -> list[str]:
    s4 = tmpl_count + 4
    lines = [
        "# Step 5 – add icon topic slide",
        *_add_slide(ex_icons, str((icons_layout or {}).get("name") or "")),
        f'get_office_element(file_path=file_path, path="/slide[{s4}]")',
        "# Find type=title shape:",
        f'set_office_property(file_path=file_path, path="/slide[{s4}]/shape[1]",',
        '                    properties={"text": "Our Strengths"})',
        "# Add SVG icons into the layout's predefined icon zones (see icon_zones in layout reference):",
    ]
    if icons_layout and icons_layout.get("icon_zones") and icon_path_example:
        icon_dir = str(Path(icon_path_example).parent)
        for zone in (icons_layout["icon_zones"] or [])[:4]:
            lines.append(f'add_office_element(file_path=file_path, parent_path="/slide[{s4}]", element_type="picture",')
            lines.append(
                f'                   properties={{"path": "{icon_dir}/<name>.svg",'
                f' "x": "{zone.get("x_cm", 0):.2f}cm", "y": "{zone.get("y_cm", 0):.2f}cm",'
                f' "width": "{zone.get("w_cm", 2.4):.2f}cm", "height": "{zone.get("h_cm", 2.4):.2f}cm"}})'
            )
    return lines


def _cleanup_and_verify_steps(tmpl_count: int) -> list[str]:
    lines = [
        "",
        f"# Step 6 – REQUIRED: remove the {tmpl_count} template example slides",
        "# After adding all content slides, delete the template slides at the start.",
        f"# Remove /slide[1] {tmpl_count} times — each removal shifts remaining slides down:",
    ]
    for _ in range(tmpl_count):
        lines.append('remove_office_element(file_path=file_path, path="/slide[1]")')
    lines += [
        "# Now slide indices restart from 1 — your first content slide is /slide[1].",
        "",
        "# Step 7 – verify",
        'get_office_element(file_path=file_path, path="/")',
        "```",
    ]
    return lines


def _example(
    layouts: list[dict[str, Any]], layout_ex: dict[str, int | None], *prefixes: str
) -> tuple[dict[str, Any] | None, int | None, str]:
    layout = first_layout(layouts, *prefixes) or first_layout(layouts, "title_only", "bullets", "")
    name = str((layout or {}).get("name") or "")
    return layout, (layout_ex.get(name) if name else None), name


def build_worked_example(
    *,
    layouts: list[dict[str, Any]],
    safe_layouts: list[dict[str, Any]],
    icon_categories_data: dict[str, list[dict[str, Any]]],
    profile_root: str,
    lean_slide_map: dict[str, int] | None = None,
    sample_slides: int = 0,
) -> tuple[list[str], int]:
    lean = lean_slide_map or {}
    layout_ex: dict[str, int | None] = {
        layout.get("name", ""): lean.get(layout.get("name", "")) or layout.get("example_slide_index")
        for layout in layouts
    }
    _title, ex_title, title_name = _example(safe_layouts, layout_ex, "title_slide")
    _section, ex_section, section_name = _example(safe_layouts, layout_ex, "section")
    _content, ex_content, content_name = _example(safe_layouts, layout_ex, "bullets")
    icons_layout, ex_icons, _icons_name = _example(safe_layouts, layout_ex, "icons_")
    tmpl_count = len(lean) if lean else sample_slides
    icon_path_example = _first_icon_path(icon_categories_data, profile_root)

    ex_lines = _create_and_title_steps(tmpl_count, ex_title, title_name)
    ex_lines += _section_and_content_steps(tmpl_count, (ex_section, section_name), (ex_content, content_name))
    ex_lines += _icon_topic_steps(tmpl_count, icons_layout, ex_icons, icon_path_example)
    ex_lines += _cleanup_and_verify_steps(tmpl_count)
    return ex_lines, tmpl_count
