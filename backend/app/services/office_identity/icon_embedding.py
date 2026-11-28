"""Put a template icon onto a slide, the way the template itself does it."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

#: Marks every picture this module writes. The gate uses it to tell a template
#: icon from a content picture: an icon is brand furniture placed on template
#: geometry, not a claim the deck makes, so the picture checks skip it.
ICON_SHAPE_NAME_PREFIX = "Octryx Icon "

#: Part names for the icons we add. The prefix keeps them clear of the
#: template's own ``image<N>.svg`` namespace, so nothing can be overwritten.
_ICON_PART_TEMPLATE = "/ppt/media/octryx-icon-{slug}.svg"

_SVG_CONTENT_TYPE = "image/svg+xml"

_NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_SVG = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"

#: The OOXML extension URI Microsoft assigns to an SVG blip. Copied from the
#: template's own icon pictures, not invented.
_SVG_EXT_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"

_VIEWBOX = re.compile(
    rb"viewBox\s*=\s*[\"']\s*[-\d.eE]+[,\s]+[-\d.eE]+[,\s]+([\d.eE]+)[,\s]+([\d.eE]+)",
)

_SAFE_SLUG = re.compile(r"[^a-z0-9_-]+")


def icon_aspect_ratio(svg_bytes: bytes) -> float:
    match = _VIEWBOX.search(svg_bytes or b"")
    if match is None:
        return 1.0
    try:
        width = float(match.group(1))
        height = float(match.group(2))
    except (TypeError, ValueError):
        return 1.0
    if width <= 0 or height <= 0:
        return 1.0
    return width / height


class IconEmbedder:
    def __init__(self, presentation: Any, template_path: str | Path) -> None:
        self._presentation = presentation
        self._template_path = Path(template_path)
        self._zip: zipfile.ZipFile | None = None
        self._parts: dict[str, Any] = {}
        self._blobs: dict[str, bytes] = {}
        self._shape_id = 9000

    # -- template access ---------------------------------------------------

    def _read(self, part_name: str) -> bytes:
        if part_name in self._blobs:
            return self._blobs[part_name]
        if self._zip is None:
            self._zip = zipfile.ZipFile(self._template_path, "r")
        try:
            blob = self._zip.read(part_name)
        except KeyError:
            blob = b""
        self._blobs[part_name] = blob
        return blob

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def __enter__(self) -> IconEmbedder:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- placement ---------------------------------------------------------

    def _image_part(self, slug: str, blob: bytes) -> Any:
        from pptx.opc.package import Part
        from pptx.opc.packuri import PackURI

        if slug in self._parts:
            return self._parts[slug]
        safe = _SAFE_SLUG.sub("-", slug.lower()).strip("-") or "icon"
        part = Part(
            PackURI(_ICON_PART_TEMPLATE.format(slug=safe)),
            _SVG_CONTENT_TYPE,
            self._presentation.part.package,
            blob,
        )
        self._parts[slug] = part
        return part

    def place(self, slide: Any, icon: dict[str, Any], rect: dict[str, int]) -> str:
        from lxml import etree
        from pptx.opc.constants import RELATIONSHIP_TYPE as RT

        slug = str(icon.get("slug") or "").strip()
        part_name = str(icon.get("part") or "").strip()
        if not slug or not part_name:
            return ""
        blob = self._read(part_name)
        if not blob:
            return ""

        part = self._image_part(slug, blob)
        rel_id = slide.part.relate_to(part, RT.IMAGE)
        self._shape_id += 1
        element = etree.fromstring(
            _PIC_XML.format(
                ns_p=_NS_P,
                ns_a=_NS_A,
                ns_r=_NS_R,
                ns_svg=_NS_SVG,
                ext_uri=_SVG_EXT_URI,
                shape_id=self._shape_id,
                name=f"{ICON_SHAPE_NAME_PREFIX}{slug}",
                rel_id=rel_id,
                x=int(rect["x_emu"]),
                y=int(rect["y_emu"]),
                cx=int(rect["w_emu"]),
                cy=int(rect["h_emu"]),
            ).encode("utf-8")
        )
        slide.shapes._spTree.append(element)
        return slug

    def aspect_ratio(self, icon: dict[str, Any]) -> float:
        return icon_aspect_ratio(self._read(str(icon.get("part") or "")))


#: The picture element, byte-shaped like the template's own icon pictures: a
#: blip with no ``r:embed`` and an SVG extension that carries the reference.
_PIC_XML = (
    '<p:pic xmlns:p="{ns_p}" xmlns:a="{ns_a}" xmlns:r="{ns_r}">'
    "<p:nvPicPr>"
    '<p:cNvPr id="{shape_id}" name="{name}"/>'
    '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
    "<p:nvPr/>"
    "</p:nvPicPr>"
    "<p:blipFill>"
    "<a:blip><a:extLst>"
    '<a:ext uri="{ext_uri}">'
    '<asvg:svgBlip xmlns:asvg="{ns_svg}" r:embed="{rel_id}"/>'
    "</a:ext>"
    "</a:extLst></a:blip>"
    "<a:stretch><a:fillRect/></a:stretch>"
    "</p:blipFill>"
    "<p:spPr>"
    '<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
    "</p:spPr>"
    "</p:pic>"
)


__all__ = ["ICON_SHAPE_NAME_PREFIX", "IconEmbedder", "icon_aspect_ratio"]
