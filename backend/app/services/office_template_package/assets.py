"""Asset extraction and indexing helpers for Office template packages."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.services.office_template_package.constants import RASTER_ASSET_SUFFIXES, SVG_NS, VECTOR_ASSET_SUFFIXES


def _normalize_asset_tokens(values: list[str]) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for value in values:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+-]{2,}", str(value or "")):
            lowered = token.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            tokens.append(lowered)
    return tokens[:40]


def _svg_text_tokens(path: Path) -> list[str]:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8", errors="ignore"))
    except ET.ParseError:
        return []
    values: list[str] = []
    for query in (".//svg:title", ".//svg:desc", ".//svg:text"):
        for node in root.findall(query, SVG_NS):
            text = "".join(node.itertext()).strip()
            if text:
                values.append(text)
    for element in root.iter():
        for key in ("id", "class", "aria-label"):
            value = element.attrib.get(key)
            if value:
                values.append(value)
    return _normalize_asset_tokens(values)


def _asset_dimensions(path: Path, suffix: str) -> tuple[int, int]:
    if suffix == ".svg":
        try:
            root = ET.fromstring(path.read_text(encoding="utf-8", errors="ignore"))
        except ET.ParseError:
            return (0, 0)
        view_box = str(root.attrib.get("viewBox") or "").strip()
        match = re.match(r"[-0-9.]+\s+[-0-9.]+\s+([0-9.]+)\s+([0-9.]+)", view_box)
        if match:
            return (int(float(match.group(1))), int(float(match.group(2))))
        width = root.attrib.get("width")
        height = root.attrib.get("height")
        try:
            return (int(float(str(width).replace("px", ""))), int(float(str(height).replace("px", ""))))
        except (TypeError, ValueError):
            return (0, 0)
    return (0, 0)


def _inferred_asset_tags(
    file_name: str, *, category: str, width: int, height: int, text_tokens: list[str]
) -> list[str]:
    seed = [file_name, *text_tokens]
    tags: set[str] = set()
    blob = " ".join(seed).lower()
    if category == "vector":
        tags.add("vector")
    if category == "raster":
        tags.add("raster")
    if width and height:
        ratio = width / max(height, 1)
        if ratio >= 2.5:
            tags.add("banner")
        if 0.85 <= ratio <= 1.15:
            tags.add("square")
        if width <= 256 and height <= 256:
            tags.add("icon")
        if width >= 1000 or height >= 700:
            tags.add("hero")
    if any(word in blob for word in ("logo", "brand", "gd")):
        tags.add("logo")
        tags.add("brand")
    if any(word in blob for word in ("device", "screen", "display", "phone", "mobile", "laptop", "monitor")):
        tags.add("device")
        tags.add("mockup")
    if any(word in blob for word in ("icon", "symbol", "glyph", "badge")):
        tags.add("icon")
    if any(word in blob for word in ("chart", "diagram", "flow", "roadmap", "timeline", "process")):
        tags.add("diagram")
    if any(word in blob for word in ("photo", "person", "team", "customer")):
        tags.add("photo")
    return sorted(tags)


def _preferred_roles_for_asset(tags: list[str]) -> list[str]:
    roles: set[str] = set()
    tag_set = set(tags)
    if {"logo", "brand"} & tag_set:
        roles.update({"title_cover", "closing_takeaway"})
    if {"device", "mockup", "hero", "photo"} & tag_set:
        roles.add("image_device_mockup")
    if {"icon", "diagram"} & tag_set:
        roles.update({"capability_cards", "integration_timeline"})
    if not roles:
        roles.update({"overview_hero", "operations_content"})
    return sorted(roles)


def _asset_index_entry(path: Path, *, category: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text_tokens = _svg_text_tokens(path) if suffix == ".svg" else []
    width, height = _asset_dimensions(path, suffix)
    tags = _inferred_asset_tags(path.name, category=category, width=width, height=height, text_tokens=text_tokens)
    return {
        "text_tokens": text_tokens,
        "width": width,
        "height": height,
        "preferred_roles": _preferred_roles_for_asset(tags),
        "tags": tags,
    }


def _extract_media(zip_file: zipfile.ZipFile, package_root: Path) -> dict[str, Any]:
    media_dir = package_root / "assets" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    media_entries: list[dict[str, Any]] = []
    for name in sorted(n for n in zip_file.namelist() if n.startswith("ppt/media/")):
        raw_name = Path(name).name
        if not raw_name:
            continue
        target = media_dir / raw_name
        target.write_bytes(zip_file.read(name))
        suffix = target.suffix.lower()
        category = (
            "vector" if suffix in VECTOR_ASSET_SUFFIXES else "raster" if suffix in RASTER_ASSET_SUFFIXES else "binary"
        )
        media_entries.append(
            {
                "source": name,
                "file_name": raw_name,
                "path": str(target),
                "suffix": suffix,
                "category": category,
                "size_bytes": target.stat().st_size,
                **_asset_index_entry(target, category=category),
            }
        )
    return {
        "all": media_entries,
        "vector": [item for item in media_entries if item["category"] == "vector"],
        "raster": [item for item in media_entries if item["category"] == "raster"],
    }
