"""OOXML part writers for the synthetic test template (``office_template_fixture``).

Plain string templates for the handful of PresentationML/DrawingML parts a
template package needs. Kept apart from the layout catalogue so each file reads
as one thing: this one knows XML, the fixture knows what the template contains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

if TYPE_CHECKING:
    from tests.office_template_layouts import Layout, Ph

NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)
_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_GROUP = (
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
    '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
)
_SVG_EXT_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"
_SVG_NS = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"

#: Made-up palette; only ``accent1`` is asserted by the tests.
_PALETTE = {
    "dk1": "000000", "lt1": "FFFFFF", "dk2": "1B2A3A", "lt2": "EEF1F4",
    "accent2": "D9822B", "accent3": "5B6C7D", "accent4": "8FB339",
    "accent5": "2E86AB", "accent6": "A23B72", "hlink": "2E86AB", "folHlink": "5B6C7D",
}
_COLOR_ORDER = ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3",
                "accent4", "accent5", "accent6", "hlink", "folHlink")


def _xfrm(rect: tuple[int, int, int, int]) -> str:
    x, y, cx, cy = rect
    return f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'


def _color(value: str) -> str:
    if value.startswith("scheme:"):
        return f'<a:solidFill><a:schemeClr val="{value.split(":", 1)[1]}"/></a:solidFill>'
    return f'<a:solidFill><a:srgbClr val="{value.lstrip("#")}"/></a:solidFill>'


def _paragraphs(lines: list[str]) -> str:
    if not lines:
        return '<a:p><a:endParaRPr lang="en-US"/></a:p>'
    return "".join(f'<a:p><a:r><a:rPr lang="en-US"/><a:t>{escape(line)}</a:t></a:r></a:p>' for line in lines)


def _ph_tag(kind: str, idx: int) -> str:
    return f'<p:ph type="{kind}"/>' if idx == 0 else f'<p:ph type="{kind}" idx="{idx}"/>'


def rels_xml(entries: list[tuple[str, str, str]]) -> str:
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{target}"/>' for i, t, target in entries)
    return f'{_DECL}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>'


def content_types_xml(overrides: dict[str, str]) -> str:
    defaults = {
        "rels": "application/vnd.openxmlformats-package.relationships+xml",
        "xml": "application/xml",
        "png": "image/png",
        "svg": "image/svg+xml",
    }
    body = "".join(f'<Default Extension="{ext}" ContentType="{ct}"/>' for ext, ct in defaults.items())
    body += "".join(f'<Override PartName="/{name}" ContentType="{ct}"/>' for name, ct in sorted(overrides.items()))
    return f'{_DECL}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">{body}</Types>'


def presentation_xml(masters: int, slide_rel_start: int, slides: int, width: int, height: int) -> str:
    master_ids = "".join(
        f'<p:sldMasterId id="{2147484648 + 1000 * (i - 1)}" r:id="rId{i}"/>' for i in range(1, masters + 1)
    )
    slide_ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{slide_rel_start + i}"/>' for i in range(slides))
    slide_list = f"<p:sldIdLst>{slide_ids}</p:sldIdLst>" if slides else ""
    return (
        f'{_DECL}<p:presentation {NS}><p:sldMasterIdLst>{master_ids}</p:sldMasterIdLst>{slide_list}'
        f'<p:sldSz cx="{width}" cy="{height}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
    )


def master_xml(layout_ids: list[tuple[int, str]], placeholders: list[Ph]) -> str:
    shapes = "".join(_layout_shape(2 + i, ph) for i, ph in enumerate(placeholders))
    ids = "".join(f'<p:sldLayoutId id="{lid}" r:id="{rid}"/>' for lid, rid in layout_ids)
    color_map = " ".join(
        f'{k}="{v}"' for k, v in (("bg1", "lt1"), ("tx1", "dk1"), ("bg2", "lt2"), ("tx2", "dk2"))
    ) + " " + " ".join(f'{slot}="{slot}"' for slot in _COLOR_ORDER[4:])
    styles = "".join(
        f"<p:{name}><a:lvl1pPr><a:defRPr sz=\"{size}\"/></a:lvl1pPr></p:{name}>"
        for name, size in (("titleStyle", 2400), ("bodyStyle", 1400), ("otherStyle", 1200))
    )
    return (
        f'{_DECL}<p:sldMaster {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:schemeClr val="bg1"/></a:solidFill>'
        f"<a:effectLst/></p:bgPr></p:bg><p:spTree>{_GROUP}{shapes}</p:spTree></p:cSld>"
        f"<p:clrMap {color_map}/><p:sldLayoutIdLst>{ids}</p:sldLayoutIdLst>"
        f"<p:txStyles>{styles}</p:txStyles></p:sldMaster>"
    )


def theme_xml(name: str, font: str, accent1: str) -> str:
    palette = {**_PALETTE, "accent1": accent1.lstrip("#")}
    colors = "".join(f'<a:{slot}><a:srgbClr val="{palette[slot]}"/></a:{slot}>' for slot in _COLOR_ORDER)
    face = f'<a:latin typeface="{font}"/><a:ea typeface=""/><a:cs typeface=""/>'
    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = f'<a:ln w="6350">{fill}</a:ln>'
    return (
        f'{_DECL}<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="{name}">'
        f'<a:themeElements><a:clrScheme name="{name}">{colors}</a:clrScheme>'
        f'<a:fontScheme name="{name}"><a:majorFont>{face}</a:majorFont><a:minorFont>{face}</a:minorFont></a:fontScheme>'
        f'<a:fmtScheme name="{name}"><a:fillStyleLst>{fill * 3}</a:fillStyleLst><a:lnStyleLst>{line * 3}</a:lnStyleLst>'
        f"<a:effectStyleLst>{'<a:effectStyle><a:effectLst/></a:effectStyle>' * 3}</a:effectStyleLst>"
        f"<a:bgFillStyleLst>{fill * 3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>"
    )


def _placeholder(
    shape_id: int, kind: str, idx: int, rect: tuple[int, int, int, int] | None,
    color: str, size: int, fill: bool, lines: list[str],
) -> str:
    geometry = _xfrm(rect) if rect else ""
    paint = '<a:solidFill><a:schemeClr val="accent1"/></a:solidFill>' if fill else ""
    run = (f' sz="{size}"' if size else "")
    level = f"<a:lvl1pPr><a:defRPr{run}>{_color(color) if color else ''}</a:defRPr></a:lvl1pPr>" if (color or size) else ""
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{kind} {idx}"/>'
        f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr>{_ph_tag(kind, idx)}</p:nvPr></p:nvSpPr>'
        f"<p:spPr>{geometry}{paint}</p:spPr>"
        f"<p:txBody><a:bodyPr/><a:lstStyle>{level}</a:lstStyle>{_paragraphs(lines)}</p:txBody></p:sp>"
    )


def _layout_shape(shape_id: int, ph: Ph) -> str:
    return _placeholder(shape_id, ph.kind, ph.idx, ph.rect, ph.color, ph.size, ph.fill, [])


def layout_xml(layout: Layout, width: int, height: int) -> str:
    layout_type = f' type="{layout.kind}"' if layout.kind else ""
    background = (
        '<p:bg><p:bgPr><a:solidFill><a:schemeClr val="accent1"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
        if layout.backdrop == "bg" else ""
    )
    shapes: list[str] = []
    if layout.backdrop == "picture":
        shapes.append(
            '<p:pic><p:nvPicPr><p:cNvPr id="2" name="Backdrop"/><p:cNvPicPr/><p:nvPr userDrawn="1"/></p:nvPicPr>'
            '<p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr>{_xfrm((0, 0, width, height))}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
        )
    shapes += [_layout_shape(10 + i, ph) for i, ph in enumerate(layout.placeholders)]
    shapes += [
        f'<p:sp><p:nvSpPr><p:cNvPr id="{40 + i}" name="Icon Holder {i + 1}"/><p:cNvSpPr/><p:nvPr userDrawn="1"/></p:nvSpPr>'
        f'<p:spPr>{_xfrm(rect)}<a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom>'
        '<a:solidFill><a:schemeClr val="lt2"/></a:solidFill></p:spPr></p:sp>'
        for i, rect in enumerate(layout.icon_holders)
    ]
    return (
        f'{_DECL}<p:sldLayout {NS}{layout_type} preserve="1"><p:cSld name="{escape(layout.name)}">{background}'
        f"<p:spTree>{_GROUP}{''.join(shapes)}</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>"
    )


def slide_xml(
    layout: Layout, texts: dict[int, list[str]], icon_labels: list[str | None], alt_texts: list[str] | None = None,
) -> str:
    """A sample slide: the layout's text placeholders (filled from ``texts``) and,
    on an icon slide, SVG pictures with an ``ICO_`` label just below-left of each
    (or, with ``alt_texts``, the picture's alt text instead of a label)."""
    shapes = [
        _placeholder(10 + i, ph.kind, ph.idx, None, "", 0, False, texts.get(ph.idx, []))
        for i, ph in enumerate(layout.placeholders)
        if ph.kind not in {"pic", "ftr", "sldNum", "dt"}
    ]
    for i, label in enumerate(icon_labels):
        x, y, size = 720_000 + i * 1_400_000, 1_440_000, 540_000
        descr = (alt_texts or [])[i] if i < len(alt_texts or []) else ""
        alt = f' descr="{escape(descr)}"' if descr else ""
        shapes.append(
            f'<p:pic><p:nvPicPr><p:cNvPr id="{60 + i}" name="Picture {i + 1}"{alt}/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip><a:extLst><a:ext uri="{_SVG_EXT_URI}">'
            f'<asvg:svgBlip xmlns:asvg="{_SVG_NS}" r:embed="rId{i + 2}"/></a:ext></a:extLst></a:blip>'
            '<a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr>{_xfrm((x, y, size, size))}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
        )
        if label:
            shapes.append(
                f'<p:sp><p:nvSpPr><p:cNvPr id="{80 + i}" name="Label {i + 1}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
                f'<p:spPr>{_xfrm((x - 182_880, y + 365_760, 900_000, 200_000))}</p:spPr>'
                f"<p:txBody><a:bodyPr/><a:lstStyle/>{_paragraphs([f'ICO_{label}'])}</p:txBody></p:sp>"
            )
    return (
        f"{_DECL}<p:sld {NS}><p:cSld><p:spTree>{_GROUP}{''.join(shapes)}</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
    )


def svg_icon(number: int) -> bytes:
    """A small, distinct vector glyph (no raster fallback, like real icon libraries)."""
    radius = 4 + number % 7
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<circle cx="12" cy="12" r="{radius}" fill="#1F6F5C"/></svg>'
    ).encode()


__all__ = [
    "content_types_xml",
    "layout_xml",
    "master_xml",
    "presentation_xml",
    "rels_xml",
    "slide_xml",
    "svg_icon",
    "theme_xml",
]
