"""Icons a template's slides reference, named by what the template says about them.

A template ships its icon library the way its author chose: a slide titled
"Icons …" with ``ICO_`` captions under each glyph, SVG pictures carrying alt
text, media files with telling names, or a mix. None of these conventions is
required here. Every SVG picture a slide references that is icon-sized becomes
a catalog entry, and its name comes from the first source that has one:

1. a caption next to the picture that carries the ``ICO_`` prefix (one
   recognised library convention, matched by proximity, not by a fixed offset),
2. the picture's alt text (``cNvPr@descr``, then ``cNvPr@title``),
3. the shape name, unless it is an editor-generated "<word> <number>" name,
4. the media file name.

Only SVG is catalogued: the composer places icons the way templates draw them —
as vector parts — and a raster picture on a sample slide is far more often a
photo than an icon.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .parsing import NS_A, NS_P, NS_R, NS_SVG, icon_slugify, ppt_text

#: An icon is at most this fraction of the slide width on its longer side
#: (a quarter of a 16:9 slide is about 6 cm — larger is an illustration).
MAX_ICON_WIDTH_RATIO = 0.25
#: Long, thin pictures are rules and banners, not icons.
MAX_ICON_ASPECT = 2.0
#: Fallback slide width when the caller does not know it (16:9, 10 inch).
DEFAULT_SLIDE_WIDTH_EMU = 9_144_000
#: A caption belongs to a picture when its centre lies within this many picture
#: sizes of the picture's centre, on each axis.
CAPTION_REACH = 1.5

_AUTO_NAME = re.compile(r"^\D+\s+\d+$")
_CAPTION = re.compile(r"^ICO_\S+", re.IGNORECASE)


def _rect(element: ET.Element) -> tuple[int, int, int, int] | None:
    props = element.find(f"{{{NS_P}}}spPr")
    transform = props.find(f"{{{NS_A}}}xfrm") if props is not None else None
    if transform is None:
        return None
    off = transform.find(f"{{{NS_A}}}off")
    ext = transform.find(f"{{{NS_A}}}ext")
    try:
        x = int(off.attrib.get("x", 0)) if off is not None else 0
        y = int(off.attrib.get("y", 0)) if off is not None else 0
        w = int(ext.attrib.get("cx", 0)) if ext is not None else 0
        h = int(ext.attrib.get("cy", 0)) if ext is not None else 0
    except (TypeError, ValueError):
        return None
    return x, y, w, h


def svg_target(picture: ET.Element, rels: dict[str, str]) -> str:
    """The SVG part a picture references (``svgBlip`` first, then a plain blip)."""
    for tag in (f"{{{NS_SVG}}}svgBlip", f"{{{NS_A}}}blip"):
        blip = picture.find(f".//{tag}")
        rel_id = str(blip.attrib.get(f"{{{NS_R}}}embed") or "").strip() if blip is not None else ""
        target = rels.get(rel_id, "") if rel_id else ""
        if target.lower().endswith(".svg"):
            return target
    return ""


def is_icon_sized(rect: tuple[int, int, int, int] | None, slide_width: int) -> bool:
    if rect is None:
        return True  # no geometry stated: the SVG itself is the evidence
    _x, _y, width, height = rect
    if width <= 0 or height <= 0:
        return True
    longer, shorter = max(width, height), min(width, height)
    limit = MAX_ICON_WIDTH_RATIO * (slide_width or DEFAULT_SLIDE_WIDTH_EMU)
    return longer <= limit and longer / shorter <= MAX_ICON_ASPECT


def _captions(root: ET.Element) -> list[tuple[str, tuple[int, int, int, int]]]:
    captions: list[tuple[str, tuple[int, int, int, int]]] = []
    for shape in root.iter(f"{{{NS_P}}}sp"):
        rect = _rect(shape)
        if rect is None:
            continue
        for token in ppt_text(shape).split():
            if _CAPTION.match(token):
                captions.append((token.strip(), rect))
                break
    return captions


def _centre(rect: tuple[int, int, int, int]) -> tuple[float, float]:
    return rect[0] + rect[2] / 2, rect[1] + rect[3] / 2


def _nearest_caption(
    rect: tuple[int, int, int, int] | None,
    captions: list[tuple[str, tuple[int, int, int, int]]],
    used: set[int],
) -> str:
    if rect is None or rect[2] <= 0 or rect[3] <= 0:
        return ""
    px, py = _centre(rect)
    best, best_distance = -1, math.inf
    for index, (_text, caption_rect) in enumerate(captions):
        if index in used:
            continue
        cx, cy = _centre(caption_rect)
        if abs(cx - px) > CAPTION_REACH * rect[2] or abs(cy - py) > CAPTION_REACH * rect[3]:
            continue
        distance = math.hypot(cx - px, cy - py)
        if distance < best_distance:
            best, best_distance = index, distance
    if best < 0:
        return ""
    used.add(best)
    return captions[best][0]


def _picture_names(picture: ET.Element) -> tuple[str, str]:
    """(alt text, meaningful shape name) of a picture; either may be empty."""
    props = picture.find(f".//{{{NS_P}}}cNvPr")
    if props is None:
        return "", ""
    alt = str(props.attrib.get("descr") or props.attrib.get("title") or "").strip()
    name = str(props.attrib.get("name") or "").strip()
    return alt.splitlines()[0].strip() if alt else "", "" if _AUTO_NAME.match(name) else name


def slide_icons(
    root: ET.Element, rels: dict[str, str], category: str, *, slide_width: int = 0
) -> list[dict[str, Any]]:
    """Every icon-sized SVG picture of one slide, named as the module docstring says.

    ``rels`` maps relationship ids to image identifiers; the value is passed
    through as ``original_file``. Pictures are returned in document order.
    """
    captions = _captions(root)
    used: set[int] = set()
    icons: list[dict[str, Any]] = []
    for picture in root.iter(f"{{{NS_P}}}pic"):
        target = svg_target(picture, rels)
        rect = _rect(picture)
        if not target or not is_icon_sized(rect, slide_width):
            continue
        caption = _nearest_caption(rect, captions, used)
        alt_text, shape_name = _picture_names(picture)
        file_name = Path(target).stem
        name = caption or alt_text or shape_name or file_name
        icons.append(
            {
                "name": name,
                "slug": icon_slugify(name)[:60],
                "original_file": target,
                "category": category,
                "alt_text": alt_text,
                "file_name": file_name,
                "name_source": "caption" if caption else "alt_text" if alt_text else "shape_name" if shape_name else "file_name",
            }
        )
    return icons


__all__ = ["is_icon_sized", "slide_icons", "svg_target"]
