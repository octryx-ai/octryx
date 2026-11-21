"""Write real ``slideLayout`` parts into a PowerPoint package.

python-pptx has no public API for adding a layout, so this module works on the
OPC package itself: a layout is created by **cloning an existing layout of the
same master** and then adjusting placeholders. Nothing about the master, the
theme, the colours, the fonts or the background is touched — the clone inherits
all of it exactly as its donor did, which is what keeps the corporate identity
intact.

Registering the authored part in the package — relationships, content type
and the master's layout list — is :mod:`.layout_registration`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from lxml import etree

NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"

#: Marker namespace and ``p:ext`` uri for layouts this module generated. ``extLst``
#: is the OOXML-sanctioned place for producer data: PowerPoint round-trips
#: unknown extensions untouched and every other consumer ignores them, so the
#: derived layout stays a completely ordinary layout to the outside world.
OCTRYX_NS = "http://octryx.local/office-identity/normalization"
OCTRYX_EXT_URI = "{4F6C9D2A-7B31-4C58-9E0D-1A2B3C4D5E6F}"

#: Placeholder types that carry the brand furniture of a slide; a generated
#: layout keeps them exactly as the donor had them.
_CHROME_TYPES = frozenset({"ftr", "sldNum", "dt", "hdr"})
_TITLE_TYPES = frozenset({"title", "ctrTitle"})

_SHAPE_TAGS = frozenset({f"{{{NS_P}}}sp", f"{{{NS_P}}}pic", f"{{{NS_P}}}graphicFrame"})


@dataclass(frozen=True)
class LayoutSpec:
    """One layout to generate.

    ``picture_rect`` is the geometry the picture placeholder receives; the
    caller measures it out of the template, this module only writes it.
    """

    name: str
    shape: str
    donor_part: str
    master_part: str
    picture_idx: int
    picture_rect: dict[str, int]
    rationale: str
    extra_marker: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratedLayout:
    """What actually landed in the package for one :class:`LayoutSpec`."""

    spec: LayoutSpec
    part: str
    rel_id: str
    layout_id: int
    removed_placeholders: tuple[int, ...]


# ---------------------------------------------------------------------------
# reading the marker back
# ---------------------------------------------------------------------------


def layout_origin(layout_root: ET.Element | None) -> dict[str, str]:
    """``origin`` fields for a layout part, for the snapshot brief.

    Returns ``{"origin": "template"}`` for every layout the template author
    wrote and ``{"origin": "derived", ...}`` for the ones normalisation added.
    """
    if layout_root is None:
        return {"origin": "template"}
    for ext in layout_root.findall(f"{{{NS_P}}}extLst/{{{NS_P}}}ext"):
        if str(ext.attrib.get("uri") or "") != OCTRYX_EXT_URI:
            continue
        marker = ext.find(f"{{{OCTRYX_NS}}}derivedLayout")
        if marker is None:
            continue
        origin = {"origin": "derived"}
        for key in ("shape", "clonedFrom"):
            value = str(marker.attrib.get(key) or "").strip()
            if value:
                origin["derived_shape" if key == "shape" else "derived_from"] = value
        return origin
    return {"origin": "template"}


# ---------------------------------------------------------------------------
# layout part authoring
# ---------------------------------------------------------------------------


def _placeholder_facts(shape: etree._Element) -> tuple[str, int] | None:
    # ``sp``, ``pic`` and ``graphicFrame`` each nest ``p:ph`` under a different
    # non-visual properties element, so the search is by descendant — the same
    # rule the snapshot reader uses.
    placeholder = shape.find(f".//{{{NS_P}}}ph")
    if placeholder is None:
        return None
    kind = str(placeholder.attrib.get("type") or "obj").strip() or "obj"
    try:
        index = int(placeholder.attrib.get("idx", 0))
    except (TypeError, ValueError):
        index = 0
    return kind, index


def _set_geometry(shape: etree._Element, rect: dict[str, int]) -> None:
    """Give the placeholder an explicit transform; create ``a:xfrm`` if absent."""
    props = shape.find(f"{{{NS_P}}}spPr")
    if props is None:
        props = etree.SubElement(shape, f"{{{NS_P}}}spPr")
    transform = props.find(f"{{{NS_A}}}xfrm")
    if transform is None:
        transform = etree.Element(f"{{{NS_A}}}xfrm")
        props.insert(0, transform)
    for child in list(transform):
        if child.tag in (f"{{{NS_A}}}off", f"{{{NS_A}}}ext"):
            transform.remove(child)
    off = etree.SubElement(transform, f"{{{NS_A}}}off")
    off.set("x", str(int(rect["x_emu"])))
    off.set("y", str(int(rect["y_emu"])))
    ext = etree.SubElement(transform, f"{{{NS_A}}}ext")
    ext.set("cx", str(int(rect["w_emu"])))
    ext.set("cy", str(int(rect["h_emu"])))


def _append_marker(root: etree._Element, spec: LayoutSpec) -> None:
    ext_list = root.find(f"{{{NS_P}}}extLst")
    if ext_list is None:
        ext_list = etree.SubElement(root, f"{{{NS_P}}}extLst")
    ext = etree.SubElement(ext_list, f"{{{NS_P}}}ext")
    ext.set("uri", OCTRYX_EXT_URI)
    marker = etree.SubElement(ext, f"{{{OCTRYX_NS}}}derivedLayout", nsmap={"octryx": OCTRYX_NS})
    marker.set("shape", spec.shape)
    marker.set("clonedFrom", spec.donor_part)
    for key in sorted(spec.extra_marker):
        marker.set(key, spec.extra_marker[key])


def build_layout_xml(donor_xml: bytes, spec: LayoutSpec) -> tuple[bytes, tuple[int, ...]]:
    """Clone ``donor_xml`` into the layout ``spec`` describes.

    Kept: the title, the chrome placeholders (footer, slide number, date) and
    the picture placeholder — the latter resized to ``spec.picture_rect``.
    Dropped: every other placeholder, because a diagram slide has nothing to
    put in them and an empty body placeholder would show its prompt text.
    Non-placeholder shapes are the donor's own design and stay untouched.
    """
    root = etree.fromstring(donor_xml)
    tree = root.find(f"{{{NS_P}}}cSld/{{{NS_P}}}spTree")
    if tree is None:
        raise ValueError(f"donor layout has no spTree: {spec.donor_part}")

    removed: list[int] = []
    picture_found = False
    for shape in list(tree.iter()):
        if shape.tag not in _SHAPE_TAGS:
            continue
        facts = _placeholder_facts(shape)
        if facts is None:
            continue
        kind, index = facts
        if index == spec.picture_idx:
            _set_geometry(shape, spec.picture_rect)
            picture_found = True
            continue
        if kind in _TITLE_TYPES or kind in _CHROME_TYPES:
            continue
        parent = shape.getparent()
        if parent is not None:
            parent.remove(shape)
            removed.append(index)
    if not picture_found:
        raise ValueError(
            f"donor layout {spec.donor_part} has no placeholder idx {spec.picture_idx}"
        )

    common = root.find(f"{{{NS_P}}}cSld")
    if common is not None:
        common.set("name", spec.name)
    # A generated layout is meant to be kept even when unused, exactly like the
    # template's own layouts.
    root.set("preserve", "1")
    _append_marker(root, spec)
    payload = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    return payload, tuple(sorted(removed))


__all__: list[str] = [
    "GeneratedLayout",
    "LayoutSpec",
    "OCTRYX_EXT_URI",
    "OCTRYX_NS",
    "build_layout_xml",
    "layout_origin",
]
