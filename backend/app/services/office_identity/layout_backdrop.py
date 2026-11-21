"""Does a slide layout paint something opaque behind its own text?

Split out of ``template_snapshot`` so the shape-tree reading that answers this
question lives with its own responsibility. The answer feeds the ``title_illegible``
gate check: a layout that declares a light title colour is only safe if there is
a backdrop behind it.
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from ..corp_identity.parsing import NS_A, NS_P

_PAINTING_FILLS = ("solidFill", "gradFill", "blipFill", "pattFill")

#: A decorative shape covering at least this fraction of the slide acts as the
#: layout's background.
BACKDROP_AREA_RATIO = 0.90

#: Theme slots that resolve to a light surface colour.
_LIGHT_SCHEME_SLOTS = frozenset({"bg1", "lt1", "bg2", "lt2"})
#: Relative luminance from which a literal colour counts as light.
_LIGHT_LUMINANCE = 0.75


def is_light_color(value: str | None) -> bool:
    """Whether a recorded slot colour is light enough to vanish on white.

    Inherited colours (``None``) are theme colours by definition and are not
    judged here; only an explicitly set scheme slot or literal RGB is.
    """
    if not value:
        return False
    if value.startswith("scheme:"):
        return value.split(":", 1)[1] in _LIGHT_SCHEME_SLOTS
    if value.startswith("#") and len(value) == 7:
        try:
            red, green, blue = (int(value[index : index + 2], 16) for index in (1, 3, 5))
        except ValueError:
            return False
        return (0.299 * red + 0.587 * green + 0.114 * blue) / 255 >= _LIGHT_LUMINANCE
    return False


def has_fill(shape: ET.Element) -> bool:
    for props_tag in (f"{{{NS_P}}}spPr", f"{{{NS_A}}}spPr"):
        props = shape.find(props_tag)
        if props is None:
            continue
        return any(props.find(f"{{{NS_A}}}{fill}") is not None for fill in _PAINTING_FILLS)
    return False


def paints_backdrop(
    root: ET.Element,
    slide_size: dict[str, Any],
    geometry: Any,
) -> bool:
    """``p:bg`` — or a slide-filling decorative shape — backs this layout's text.

    Templates just as often place a full-slide picture or filled rectangle in
    the layout's shape tree as they set ``p:bg``; a branded title slide often
    does exactly that (a full-slide ``p:pic`` behind a light title), which is
    why its title is legible. Reading only ``p:bg`` reported such a slide as
    ``title_illegible`` although the render shows the light title on the
    backdrop picture.

    Non-placeholder shapes only: a *placeholder* that happens to be large is
    content, not decoration. ``geometry`` is the shape-transform reader of the
    snapshot, passed in so this module stays free of the snapshot's internals.
    """
    if root.find(f"{{{NS_P}}}cSld/{{{NS_P}}}bg") is not None:
        return True
    slide_area = int(slide_size.get("width_emu") or 0) * int(slide_size.get("height_emu") or 0)
    tree = root.find(f".//{{{NS_P}}}spTree")
    if tree is None or slide_area <= 0:
        return False
    for shape in tree:
        tag = shape.tag.split("}")[-1]
        if tag not in {"sp", "pic"}:
            continue
        if shape.find(f".//{{{NS_P}}}ph") is not None:
            continue
        if tag == "sp" and not has_fill(shape):
            continue
        rect = geometry(shape)
        if rect and (rect["w_emu"] * rect["h_emu"]) / slide_area >= BACKDROP_AREA_RATIO:
            return True
    return False


__all__ = ["BACKDROP_AREA_RATIO", "has_fill", "is_light_color", "paints_backdrop"]
