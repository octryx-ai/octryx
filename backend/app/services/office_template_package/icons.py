"""Icon catalog extraction from PPT template slides."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.services.corp_identity.icons import slide_icon_category
from app.services.corp_identity.slide_icons import slide_icons
from app.services.office_template_package.constants import NS_P

#: Package-generated media names (``image7``) say nothing about the icon.
_GENERATED_FILE_NAME = re.compile(r"^[A-Za-z]+\d+$")


def _icon_slugify(value: str) -> str:
    cleaned = re.sub(r"^ICO_", "", str(value or "").strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"[^\w\-]", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned.lower() or "icon"


def _load_rels(rels_path: Path) -> dict[str, str]:
    rels: dict[str, str] = {}
    if not rels_path.exists():
        return rels
    tree = ET.parse(rels_path)
    for rel in tree.getroot():
        rid = rel.get("Id", "")
        target = rel.get("Target", "")
        target = re.sub(r"^\.\./media/", "", target)
        target = re.sub(r"^media/", "", target)
        if rid:
            rels[rid] = target
    return rels


def _slide_width(extracted_ppt_dir: Path) -> int:
    try:
        size = ET.parse(extracted_ppt_dir / "presentation.xml").getroot().find(f"{{{NS_P}}}sldSz")
        return int(size.get("cx", 0)) if size is not None else 0
    except (OSError, ET.ParseError, TypeError, ValueError):
        return 0


def _detect_icon_slides(extracted_ppt_dir: Path) -> list[tuple[Path, Path, str]]:
    slides_dir = extracted_ppt_dir / "slides"
    rels_dir = slides_dir / "_rels"
    results: list[tuple[Path, Path, str]] = []
    for slide_file in sorted(slides_dir.glob("slide*.xml"), key=lambda path: int(re.sub(r"\D", "", path.stem) or 0)):
        try:
            root = ET.parse(slide_file).getroot()
        except ET.ParseError:
            continue
        results.append((slide_file, rels_dir / f"{slide_file.name}.rels", slide_icon_category(root)))
    return results


def _parse_icon_slide(
    slide_xml: Path, rels_path: Path, category: str, slide_width: int = 0
) -> list[dict[str, Any]]:
    try:
        root = ET.parse(slide_xml).getroot()
    except ET.ParseError:
        return []
    icons: list[dict[str, Any]] = []
    for icon in slide_icons(root, _load_rels(rels_path), category, slide_width=slide_width):
        name = str(icon.get("name") or "").strip()
        named = icon.get("name_source") != "file_name" or not _GENERATED_FILE_NAME.match(name)
        icons.append(
            {
                "name": name if named else str(icon.get("original_file") or ""),
                "label": name if named else "",
                "slug": _icon_slugify(name),
                "file": icon.get("original_file"),
                "category": category,
                "slide": slide_xml.stem,
            }
        )
    return icons


def _store_named_icon(
    icon: dict[str, Any], media_dir: Path, icons_dir: Path, package_root: Path,
    categories: dict[str, list[dict[str, Any]]],
) -> None:
    src = media_dir / str(icon.get("file") or "")
    if not src.exists():
        return
    category_slug = _icon_slugify(str(icon.get("category") or "general"))
    category_dir = icons_dir / category_slug
    category_dir.mkdir(parents=True, exist_ok=True)
    dest = category_dir / f"{icon['slug']}.svg"
    counter = 1
    while dest.exists() and dest.read_bytes() != src.read_bytes():
        dest = category_dir / f"{icon['slug']}_{counter}.svg"
        counter += 1
    shutil.copy2(src, dest)
    icon["named_path"] = str(dest.relative_to(package_root))
    categories.setdefault(str(icon["category"] or "General"), []).append(
        {
            "name": icon["name"],
            "slug": icon["slug"],
            "original_file": icon["file"],
            "named_path": icon["named_path"],
        }
    )


def _copy_named_icon_catalog(package_root: Path, extracted_root: Path) -> dict[str, Any]:
    ppt_dir = extracted_root / "ppt"
    media_dir = ppt_dir / "media"
    icons_dir = package_root / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = icons_dir / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    svg_count = 0
    for svg_file in media_dir.glob("*.svg"):
        shutil.copy2(svg_file, raw_dir / svg_file.name)
        svg_count += 1

    icon_slides = _detect_icon_slides(ppt_dir)
    slide_width = _slide_width(ppt_dir)
    all_icons: list[dict[str, Any]] = []
    for slide_xml, rels_path, category in icon_slides:
        all_icons.extend(_parse_icon_slide(slide_xml, rels_path, category, slide_width))

    seen_slugs: dict[str, dict[str, Any]] = {}
    unique_icons: list[dict[str, Any]] = []
    unlabeled_icons: list[dict[str, Any]] = []
    for icon in all_icons:
        if not icon.get("label"):
            unlabeled_icons.append(icon)
            continue
        slug = str(icon.get("slug") or "")
        if slug not in seen_slugs:
            seen_slugs[slug] = icon
            unique_icons.append(icon)

    catalog: dict[str, Any] = {
        "total_icons": len(unique_icons),
        "raw_svg_count": svg_count,
        "categories": {},
    }
    for icon in unique_icons:
        _store_named_icon(icon, media_dir, icons_dir, package_root, catalog["categories"])

    catalog_path = icons_dir / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "catalog_path": str(catalog_path),
        "icon_count": len(unique_icons),
        "raw_svg_count": svg_count,
        "categories": catalog["categories"],
        "named_icons": unique_icons,
        "unlabeled_icons": unlabeled_icons,
    }
