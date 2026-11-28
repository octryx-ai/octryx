"""A synthetic corporate PowerPoint template (variants ``brand``, ``library``, ``neutral``), written as plain OOXML at
test time; every name, colour, font and coordinate is made up."""

from __future__ import annotations

import struct
import zipfile
import zlib
from dataclasses import dataclass, field, replace
from pathlib import Path

from tests.support.office_template_layouts import (
    BRAND_ACCENT1,
    BRAND_FONT,
    BRAND_SAMPLES,
    GUTTER,
    LIBRARY_ICON_SLIDES,
    LIBRARY_SAMPLES,
    NEUTRAL_ICON_SLIDE,
    NEUTRAL_KINDS,
    SLIDE_H,
    SLIDE_W,
    THEME_NAME,
    Layout,
    brand_layouts,
    master_placeholders,
    second_master_layouts,
)
from tests.support.office_template_parts import (
    content_types_xml,
    layout_xml,
    master_xml,
    presentation_xml,
    rels_xml,
    slide_xml,
    svg_icon,
    theme_xml,
)


@dataclass
class _Package:
    parts: dict[str, bytes] = field(default_factory=dict)
    overrides: dict[str, str] = field(default_factory=dict)

    def add(self, name: str, xml: str, content_type: str = "") -> None:
        self.parts[name] = xml.encode("utf-8")
        if content_type:
            self.overrides[name] = content_type


_FIXED_DATE = (2026, 1, 1, 0, 0, 0)
_CT = "application/vnd.openxmlformats-officedocument.presentationml."
_RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def png_bytes(width: int = 16, height: int = 9, rgb: tuple[int, int, int] = (31, 111, 92)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        return struct.pack(">I", len(payload)) + tag + payload + crc

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def write_template(path: Path, variant: str = "brand") -> Path:
    if variant not in {"brand", "library", "neutral"}:
        raise ValueError(f"unknown template variant {variant!r}")
    masters = [brand_layouts()] + ([second_master_layouts()] if variant == "library" else [])
    if variant == "neutral":
        masters = [[_neutral(layout, number) for number, layout in enumerate(brand_layouts(), start=1)]]
    package = _Package()
    package.parts["ppt/media/image1.png"] = png_bytes()
    layout_parts: dict[tuple[int, str], tuple[str, Layout]] = {}
    number = 0
    for master_index, layouts in enumerate(masters, start=1):
        master_part = f"ppt/slideMasters/slideMaster{master_index}.xml"
        master_rels: list[tuple[str, str, str]] = []
        for layout in layouts:
            number += 1
            part = f"ppt/slideLayouts/slideLayout{number}.xml"
            layout_parts[(master_index, _ORIGINAL.get(layout.name, layout.name))] = (part, layout)
            rels = [("rId1", _RT + "slideMaster", f"../slideMasters/slideMaster{master_index}.xml")]
            if layout.backdrop == "picture":
                rels.append(("rId2", _RT + "image", "../media/image1.png"))
            package.add(part, layout_xml(layout, SLIDE_W, SLIDE_H), _CT + "slideLayout+xml")
            package.add(f"ppt/slideLayouts/_rels/slideLayout{number}.xml.rels", rels_xml(rels))
            master_rels.append((f"rId{len(master_rels) + 1}", _RT + "slideLayout", f"../slideLayouts/slideLayout{number}.xml"))
        theme_rel = (f"rId{len(master_rels) + 1}", _RT + "theme", f"../theme/theme{master_index}.xml")
        layout_ids = [2147483649 + 100 * master_index + i for i in range(len(layouts))]
        package.add(
            master_part, master_xml(list(zip(layout_ids, [r[0] for r in master_rels])), master_placeholders()),
            _CT + "slideMaster+xml",
        )
        package.add(f"ppt/slideMasters/_rels/slideMaster{master_index}.xml.rels", rels_xml([*master_rels, theme_rel]))
        package.add(f"ppt/theme/theme{master_index}.xml", theme_xml(THEME_NAME, BRAND_FONT, BRAND_ACCENT1),
                    "application/vnd.openxmlformats-officedocument.theme+xml")

    slides: list[str] = []
    samples = LIBRARY_SAMPLES if variant == "library" else BRAND_SAMPLES
    for master_index, name, texts in samples:
        slides.append(_add_slide(package, len(slides) + 1, layout_parts[(master_index, name)], texts, []))
    title_only = layout_parts[(1, "Title Only")]
    for title, icons, alts in _icon_slides(package, variant):
        slides.append(_add_slide(package, len(slides) + 1, title_only, {0: [title]}, icons, alts))

    pres_rels = [(f"rId{i}", _RT + "slideMaster", f"slideMasters/slideMaster{i}.xml") for i in range(1, len(masters) + 1)]
    slide_rel_start = len(pres_rels) + 1
    pres_rels += [(f"rId{slide_rel_start + i}", _RT + "slide", f"slides/slide{i + 1}.xml") for i in range(len(slides))]
    pres_rels.append((f"rId{len(pres_rels) + 1}", _RT + "theme", "theme/theme1.xml"))
    package.add(
        "ppt/presentation.xml",
        presentation_xml(len(masters), slide_rel_start, len(slides), SLIDE_W, SLIDE_H),
        _CT + "template.main+xml",
    )
    package.add("ppt/_rels/presentation.xml.rels", rels_xml(pres_rels))
    package.add("_rels/.rels", rels_xml([("rId1", _RT + "officeDocument", "ppt/presentation.xml")]))
    package.add("[Content_Types].xml", content_types_xml(package.overrides))

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["[Content_Types].xml", *sorted(n for n in package.parts if n != "[Content_Types].xml")]:
            archive.writestr(zipfile.ZipInfo(name, _FIXED_DATE), package.parts[name], zipfile.ZIP_DEFLATED)
    return path


def _icon_slides(
    package: _Package, variant: str
) -> list[tuple[str, list[tuple[str | None, str]], list[str] | None]]:
    result: list[tuple[str, list[tuple[str | None, str]], list[str] | None]] = []
    if variant == "library":
        svg_number = 0
        for title, labels in LIBRARY_ICON_SLIDES:
            icons: list[tuple[str | None, str]] = []
            for label in labels:
                svg_number += 1
                media = f"ppt/media/image{svg_number + 1}.svg"
                package.parts[media] = svg_icon(svg_number)
                icons.append((label, media))
            result.append((title, icons, None))
    if variant == "neutral":
        title, entries = NEUTRAL_ICON_SLIDE
        icons = []
        for index, (_alt, stem) in enumerate(entries, start=1):
            media = f"ppt/media/{stem}.svg"
            package.parts[media] = svg_icon(index)
            icons.append((None, media))
        result.append((title, icons, [alt for alt, _stem in entries]))
    return result


_ORIGINAL: dict[str, str] = {}


def _neutral(layout: Layout, number: int) -> Layout:
    name = f"Layout {number}"
    _ORIGINAL[name] = layout.name
    return replace(layout, name=name, kind=NEUTRAL_KINDS.get(layout.name, ""))


def _add_slide(
    package: _Package, number: int, layout: tuple[str, Layout], texts: dict[int, list[str]],
    icons: list[tuple[str | None, str]], alt_texts: list[str] | None = None,
) -> str:
    layout_part, spec = layout
    part = f"ppt/slides/slide{number}.xml"
    rels = [("rId1", _RT + "slideLayout", "../" + layout_part.removeprefix("ppt/"))]
    rels += [(f"rId{i + 2}", _RT + "image", "../media/" + Path(media).name) for i, (_label, media) in enumerate(icons)]
    package.add(part, slide_xml(spec, texts, [label for label, _media in icons], alt_texts), _CT + "slide+xml")
    package.add(f"ppt/slides/_rels/slide{number}.xml.rels", rels_xml(rels))
    return part


__all__ = [
    "BRAND_ACCENT1",
    "BRAND_FONT",
    "GUTTER",
    "SLIDE_H",
    "SLIDE_W",
    "THEME_NAME",
    "png_bytes",
    "write_template",
]
