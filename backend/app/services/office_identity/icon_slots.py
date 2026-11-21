"""Icon anchors of a layout, and which catalog icon belongs on one.

Topic layouts often draw one circle above each of their text columns. Those
circles are typically **not placeholders**: they are static ``p:sp`` autoshapes
with an ``ellipse`` (or rounded-square) preset, small and square, sitting in
the layout's shape tree next to the real body placeholders. The composer addresses placeholders by
``idx``, so it never reached them and the circles rendered empty — and the
slide looked sketchy.

This module supplies the two deterministic halves of the fix:

1. **Where** an icon goes — ``icon_anchors()`` reads those static circles out of
   the layout and records their geometry, so placement uses the template's own
   coordinates and never an invented one.
2. **Which** icon goes there — ``select_icon()`` maps a closed topic key to a
   closed, ordered list of plain synonyms (``icon_topics``) and takes the first
   catalog icon whose own words — slug, name, alt text, file name — carry one.

Both halves are deterministic and work against fixed vocabularies. There is no scoring,
no fuzzy match and no model in the path: a topic either names an icon this
template ships, or it does not. When it does not, nothing is placed and the
caller reports ``icons_unavailable`` — a foreign graphic or an emoji would be
exactly the invented content the whole package exists to prevent.
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from ..corp_identity.parsing import NS_A, NS_P
from .icon_topics import TOPIC_SYNONYMS, match_topic_icon

#: Preset geometries that count as an icon holder: the circle most templates
#: draw, and the rounded square that is the same idea drawn differently.
ICON_ANCHOR_PRESETS = frozenset({"ellipse", "roundRect"})

#: An anchor much larger than this fraction of the slide is a decorative panel,
#: not an icon holder. Typical holders cover about 1 % of the slide area; the
#: bound is generous and only excludes large decorative ovals.
MAX_ANCHOR_AREA_RATIO = 0.08

#: An anchor has to be roughly square: an icon is drawn into a circle, and a
#: long thin ellipse is a decorative rule.
MAX_ANCHOR_ASPECT = 1.35

MAX_ANCHORS_PER_LAYOUT = 12

#: How much of the anchor's box the icon is allowed to occupy. A square
#: inscribed in a circle would be 0.707 of the diameter and touches the ring on
#: all four corners; 0.5 keeps visible air between glyph and ring, which is how
#: the template's own icon slides are drawn. Verified in the render.
ICON_FILL_RATIO = 0.5

#: Closed topic vocabulary (topic key -> ordered synonyms), see ``icon_topics``.
ICON_TOPICS = TOPIC_SYNONYMS


# ---------------------------------------------------------------------------
# anchors: where the template puts an icon
# ---------------------------------------------------------------------------


def _is_placeholder(shape: ET.Element) -> bool:
    properties = shape.find(f"{{{NS_P}}}nvSpPr")
    if properties is None:
        return False
    non_visual = properties.find(f"{{{NS_P}}}nvPr")
    return non_visual is not None and non_visual.find(f"{{{NS_P}}}ph") is not None


def _preset(shape: ET.Element) -> str:
    properties = shape.find(f"{{{NS_P}}}spPr")
    if properties is None:
        return ""
    geometry = properties.find(f"{{{NS_A}}}prstGeom")
    if geometry is None:
        return ""
    return str(geometry.attrib.get("prst") or "")


def icon_anchors(
    layout_root: ET.Element,
    slide_size: dict[str, int],
    geometry: Any,
) -> list[dict[str, int]]:
    """Static icon holders of one layout, left to right then top to bottom.

    ``geometry`` is the snapshot's own shape-transform reader, passed in so this
    module does not duplicate that parsing. Only non-placeholder autoshapes with
    an icon-shaped preset and a real transform qualify; everything else in the
    shape tree is left alone.
    """
    common = layout_root.find(f"{{{NS_P}}}cSld")
    tree = common.find(f"{{{NS_P}}}spTree") if common is not None else None
    if tree is None:
        return []
    slide_area = int(slide_size.get("width_emu") or 0) * int(slide_size.get("height_emu") or 0)
    anchors: list[dict[str, int]] = []
    for shape in tree:
        if not str(shape.tag).endswith("}sp") or _is_placeholder(shape):
            continue
        if _preset(shape) not in ICON_ANCHOR_PRESETS:
            continue
        rect = geometry(shape)
        if rect is None:
            continue
        width = int(rect.get("w_emu") or 0)
        height = int(rect.get("h_emu") or 0)
        if width <= 0 or height <= 0:
            continue
        if slide_area > 0 and (width * height) / slide_area > MAX_ANCHOR_AREA_RATIO:
            continue
        longer, shorter = max(width, height), min(width, height)
        if shorter <= 0 or longer / shorter > MAX_ANCHOR_ASPECT:
            continue
        anchors.append(
            {
                "x_emu": int(rect.get("x_emu") or 0),
                "y_emu": int(rect.get("y_emu") or 0),
                "w_emu": width,
                "h_emu": height,
            }
        )
    anchors.sort(key=lambda anchor: (anchor["x_emu"], anchor["y_emu"]))
    return anchors[:MAX_ANCHORS_PER_LAYOUT]


# ---------------------------------------------------------------------------
# selection: which catalog icon belongs on a topic
# ---------------------------------------------------------------------------


def select_icon(snapshot: dict[str, Any], topic_key: str) -> dict[str, Any] | None:
    """The catalog icon for a topic key, or ``None``.

    ``None`` is a real answer, not a failure to try: it means this template
    ships no icon this closed vocabulary names for that topic. The caller must
    then place nothing and say so.
    """
    return match_topic_icon(snapshot.get("icons") or (), topic_key)


def icon_fit_rect(anchor: dict[str, int], aspect: float) -> dict[str, int]:
    """Centre an icon of ``aspect`` (w/h) inside ``anchor``, never distorting it.

    The icon is fitted into the square box ``ICON_FILL_RATIO`` of the anchor and
    centred on the anchor's centre, so it sits concentric with the template's
    circle whatever its own proportions are.
    """
    box = int(min(anchor["w_emu"], anchor["h_emu"]) * ICON_FILL_RATIO)
    ratio = aspect if aspect and aspect > 0 else 1.0
    if ratio >= 1.0:
        width = box
        height = max(1, int(round(box / ratio)))
    else:
        height = box
        width = max(1, int(round(box * ratio)))
    return {
        "x_emu": anchor["x_emu"] + (anchor["w_emu"] - width) // 2,
        "y_emu": anchor["y_emu"] + (anchor["h_emu"] - height) // 2,
        "w_emu": width,
        "h_emu": height,
    }


def plan_icon_placements(
    layout: dict[str, Any], topic_keys: list[str], snapshot: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Pair this layout's anchors with the icons its topics name.

    Returns ``(placements, unresolved)``. ``placements`` carries one
    ``{anchor, icon, topic_key}`` per anchor that got an icon, in anchor order;
    ``unresolved`` names the topic keys that found none. A layout without
    anchors yields no placements and no unresolved keys — there is nothing to
    fill, so nothing is missing.
    """
    anchors = [
        anchor for anchor in (layout.get("icon_anchors") or ()) if isinstance(anchor, dict)
    ]
    if not anchors:
        return [], []
    placements: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for anchor, topic_key in zip(anchors, topic_keys):
        key = str(topic_key or "").strip()
        if not key:
            continue
        icon = select_icon(snapshot, key)
        if icon is None:
            unresolved.append(key)
            continue
        placements.append({"anchor": anchor, "icon": icon, "topic_key": key})
    return placements, unresolved


def place_layout_icons(
    embedder: Any,
    slide: Any,
    layout: dict[str, Any],
    topic_keys: list[str],
    snapshot: dict[str, Any],
    slide_index: int,
    applied: list[str],
) -> list[dict[str, Any]]:
    """Fill a slide's static icon holders from the template's icon catalog.

    ``embedder`` is an ``icon_embedding.IconEmbedder`` (passed in so this module
    keeps no OOXML dependency of its own). A holder is filled only when the
    catalog contains an icon the slide's closed topic key names; every gap — a
    topic naming no shipped icon, or a template with no catalog — becomes an
    ``icons_unavailable`` info finding and an empty circle, never a substitute
    graphic. Placement labels are appended to ``applied`` so the composer's
    ``filled_slots`` records exactly which icons landed.
    """
    keys = [str(key or "").strip() for key in (topic_keys or [])]
    anchors = [anchor for anchor in (layout.get("icon_anchors") or ()) if isinstance(anchor, dict)]
    if not anchors or not any(keys):
        return []
    placements, unresolved = plan_icon_placements(layout, keys, snapshot)
    key = str(layout.get("key"))
    placed = 0
    for placement in placements:
        icon = placement["icon"]
        rect = icon_fit_rect(placement["anchor"], embedder.aspect_ratio(icon))
        slug = embedder.place(slide, icon, rect)
        if not slug:
            unresolved.append(placement["topic_key"])
            continue
        placed += 1
        applied.append(f"icon:{slug}@{placement['topic_key']}")
    if placed:
        applied.append(f"icons@{key}={placed}")
    if not unresolved:
        return []
    return [
        {
            "code": "icons_unavailable",
            "slide_index": slide_index,
            "layout_key": key,
            "slot_idx": None,
            "severity": "info",
            "message": (
                f"layout {key!r} has icon holders for topic(s) {sorted(set(unresolved))} "
                "but this template's icon catalog ships no matching icon; the holders "
                "stay empty rather than carrying a substitute graphic"
            ),
        }
    ]


__all__ = [
    "ICON_ANCHOR_PRESETS",
    "ICON_FILL_RATIO",
    "ICON_TOPICS",
    "MAX_ANCHORS_PER_LAYOUT",
    "icon_anchors",
    "icon_fit_rect",
    "place_layout_icons",
    "plan_icon_placements",
    "select_icon",
]
