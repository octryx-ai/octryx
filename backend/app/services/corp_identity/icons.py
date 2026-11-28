"""Icon extraction helpers for corporate identity templates."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .parsing import (
    NS_P,
    load_rels,
    placeholder_meta,
    ppt_text,
    slugify,
    xml_root,
)
from .slide_icons import slide_icons


def icon_slide_category(root: ET.Element) -> str | None:
    title_text = ""
    for shape in root.findall(f".//{{{NS_P}}}sp"):
        placeholder = placeholder_meta(shape)
        if placeholder is None:
            continue
        if placeholder[0] in {"title", "ctrTitle"}:
            title_text = ppt_text(shape)
            break
    all_text = ppt_text(root).lower()
    if "icons" not in title_text.lower() and "icons" not in all_text:
        return None
    category = re.sub(r"^\s*icons\s*", "", title_text, flags=re.IGNORECASE)
    category = re.sub(r"new\s*[–-]\s*", "", category, flags=re.IGNORECASE).strip()
    category = re.sub(r"^\d+\s*", "", category).strip() or "General"
    return category


def slide_icon_category(root: ET.Element) -> str:
    return icon_slide_category(root) or "General"


def _slide_width(slides_dir: Path) -> int:
    presentation = xml_root(slides_dir.parent / "presentation.xml")
    size = presentation.find(f"{{{NS_P}}}sldSz") if presentation is not None else None
    try:
        return int(size.attrib.get("cx", 0)) if size is not None else 0
    except (TypeError, ValueError):
        return 0


def detect_icon_slides(slides_dir: Path) -> list[tuple[Path, Path, str]]:
    rels_dir = slides_dir / "_rels"
    matches: list[tuple[Path, Path, str]] = []
    for slide_path in sorted(
        slides_dir.glob("slide*.xml"), key=lambda path: int("".join(ch for ch in path.stem if ch.isdigit()) or "0")
    ):
        if "_rels" in slide_path.parts:
            continue
        root = xml_root(slide_path)
        if root is None:
            continue
        matches.append((slide_path, rels_dir / f"{slide_path.name}.rels", slide_icon_category(root)))
    return matches


def parse_icon_slide(
    slide_path: Path, rels_path: Path, category: str, *, slide_width: int = 0
) -> list[dict[str, Any]]:
    root = xml_root(slide_path)
    if root is None:
        return []
    return icons_from_slide(root, load_rels(rels_path), category, slide_width=slide_width)


def icons_from_slide(
    root: ET.Element, rels: dict[str, str], category: str, *, slide_width: int = 0
) -> list[dict[str, Any]]:
    return slide_icons(root, rels, category, slide_width=slide_width)


def extract_icon_catalog(extracted_root: Path, profile_root: Path) -> dict[str, Any]:
    slides_dir = extracted_root / "ppt" / "slides"
    media_dir = extracted_root / "ppt" / "media"
    icons_root = profile_root / "icons"
    raw_root = icons_root / "_raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    raw_svg_count = 0
    for svg_path in media_dir.glob("*.svg"):
        shutil.copy2(svg_path, raw_root / svg_path.name)
        raw_svg_count += 1
    collected: list[dict[str, Any]] = []
    slide_width = _slide_width(slides_dir)
    for slide_path, rels_path, category in detect_icon_slides(slides_dir):
        collected.extend(parse_icon_slide(slide_path, rels_path, category, slide_width=slide_width))
    seen_slugs: set[str] = set()
    categories: dict[str, list[dict[str, Any]]] = {}
    for icon in collected:
        slug = str(icon.get("slug") or "").strip()
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        source = media_dir / str(icon.get("original_file") or "")
        if not source.exists():
            continue
        category_name = str(icon.get("category") or "General").strip() or "General"
        category_slug = slugify(category_name, fallback="general")
        category_dir = icons_root / category_slug
        category_dir.mkdir(parents=True, exist_ok=True)
        destination = category_dir / f"{slug}.svg"
        counter = 2
        while destination.exists() and destination.read_bytes() != source.read_bytes():
            destination = category_dir / f"{slug}-{counter}.svg"
            counter += 1
        shutil.copy2(source, destination)
        categories.setdefault(category_name, []).append(
            {
                "name": str(icon.get("name") or slug).strip(),
                "slug": destination.stem,
                "original_file": str(icon.get("original_file") or ""),
                "named_path": str(destination.relative_to(profile_root)),
            }
        )
    return {
        "total_icons": sum(len(items) for items in categories.values()),
        "raw_svg_count": raw_svg_count,
        "categories": categories,
    }
