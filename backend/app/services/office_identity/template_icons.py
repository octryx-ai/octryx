"""Icon catalog of a template: every icon its slides reference."""

from __future__ import annotations

import re
from typing import Any

from ..corp_identity.icons import slide_icon_category
from ..corp_identity.parsing import icon_slugify, slugify
from ..corp_identity.slide_icons import slide_icons
from .package import PresentationPackage

MAX_ICONS = 1000


#: Package-generated media names (``image7``) say nothing about the icon.
_GENERATED_FILE_NAME = re.compile(r"^[A-Za-z]+\d+$")


def _icon_tags(icon: dict[str, Any], category: str) -> list[str]:
    file_name = str(icon.get("file_name") or "")
    if _GENERATED_FILE_NAME.match(file_name):
        file_name = ""
    raw = " ".join(
        [str(icon.get("name") or ""), str(icon.get("alt_text") or ""), file_name]
        + [slugify(category, fallback="general")]
    )
    tokens = icon_slugify(raw).replace("_", "-").split("-")
    return sorted({token for token in tokens if len(token) > 1})[:12]


def _extract_icons(
    package: PresentationPackage, warnings: list[str], slide_width: int = 0
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for slide_part in package.slide_parts():
        root = package.xml(slide_part)
        if root is None:
            continue
        rels = package.rels(slide_part)
        collected.extend(
            slide_icons(root, rels, slide_icon_category(root), slide_width=slide_width)
        )
    icons: list[dict[str, Any]] = []
    seen: set[str] = set()
    for icon in collected:
        slug = str(icon.get("slug") or "").strip()
        part = str(icon.get("original_file") or "").strip()
        if not slug or slug in seen or part in seen or part not in package.names:
            continue
        seen.update({slug, part})
        category = str(icon.get("category") or "General").strip() or "General"
        icons.append(
            {
                "slug": slug,
                "name": str(icon.get("name") or slug).strip(),
                "category": category,
                "category_key": slugify(category, fallback="general"),
                "part": part,
                "tags": _icon_tags(icon, category),
            }
        )
    icons.sort(key=lambda item: (item["category_key"], item["slug"]))
    if len(icons) > MAX_ICONS:
        warnings.append(f"icon catalog truncated to {MAX_ICONS} of {len(icons)} icons")
    return icons[:MAX_ICONS]


__all__ = ["MAX_ICONS", "_extract_icons"]
