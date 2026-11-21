"""Build the tracked neutral presentation template, deterministically (O1).

The platform ships one neutral PowerPoint template so a deck can be composed before any corporate
identity is uploaded: ``fallback_templates/neutral-presentation.potx``. Which template applies is an
admin setting (``services/office/presentation_fallback.py``); this module only builds the file.

Provenance: the source is ``pptx/templates/default.pptx`` from python-pptx (MIT licence,
https://github.com/scanny/python-pptx), the locked runtime dependency (``backend/uv.lock``). It is
the plain Office theme with 11 standard layouts and no slides, brand, logo or content. The build
transforms it at the XML level only:

- the slide size becomes 16:9 widescreen (12192000 x 6858000 EMU), and every master and layout
  shape is widened by the same factor (4/3) so the layouts fill the wider slide;
- the python-pptx thumbnail and the printer-settings blob are dropped (relationships included);
- the core properties name Octryx and a fixed date instead of the upstream author;
- the package is marked as a template (``presentationml.template.main+xml``), i.e. a ``.potx``.

The output is reproducible: members keep the source order, carry a fixed timestamp and fixed
attributes, and every transformation is a pure function of the source bytes.
``tests/test_neutral_presentation_template.py`` rebuilds the file and compares it member by member
with the tracked copy, so a changed python-pptx source or builder fails until the file is rebuilt:

    cd backend && .venv/bin/python -m app.services.office.neutral_presentation_template
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable
from importlib import metadata, resources
from pathlib import Path

NEUTRAL_TEMPLATE_PATH = Path(__file__).resolve().parent / "fallback_templates" / "neutral-presentation.potx"

_SOURCE_WIDTH = 9144000
_TARGET_WIDTH = 12192000
_SLIDE_HEIGHT = 6858000
_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_FIXED_DATE = "2026-10-01T00:00:00Z"

_DROPPED_MEMBERS = frozenset({"docProps/thumbnail.jpeg", "ppt/printerSettings/printerSettings1.bin"})
_WIDENED_PARTS = re.compile(r"^ppt/(slideMasters/slideMaster\d+|slideLayouts/slideLayout\d+)\.xml$")
_HORIZONTAL_ATTRIBUTES = re.compile(r'(<a:(?:off|chOff) x=")(\d+)(")|(<a:(?:ext|chExt) cx=")(\d+)(")')
_RELATIONSHIP = re.compile(r"<Relationship [^>]*/>")


def _source_bytes() -> bytes:
    return (resources.files("pptx") / "templates" / "default.pptx").read_bytes()


def _widen(match: re.Match[str]) -> str:
    prefix, value, suffix = (match.group(1), match.group(2), match.group(3))
    if prefix is None:
        prefix, value, suffix = (match.group(4), match.group(5), match.group(6))
    return f"{prefix}{int(value) * _TARGET_WIDTH // _SOURCE_WIDTH}{suffix}"


def _widen_part(xml: str) -> str:
    return _HORIZONTAL_ATTRIBUTES.sub(_widen, xml)


def _drop_relationships(xml: str, targets: tuple[str, ...]) -> str:
    return _RELATIONSHIP.sub(lambda match: "" if any(t in match.group(0) for t in targets) else match.group(0), xml)


def _presentation(xml: str) -> str:
    return re.sub(
        r'<p:sldSz cx="\d+" cy="\d+"(?: type="[^"]*")?/>',
        f'<p:sldSz cx="{_TARGET_WIDTH}" cy="{_SLIDE_HEIGHT}"/>',
        xml,
    )


def _core_properties(_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:title>Octryx neutral presentation template</dc:title>"
        "<dc:creator>Octryx</dc:creator>"
        "<dc:description>Neutral fallback template, derived from the python-pptx default template "
        "(MIT).</dc:description>"
        "<cp:lastModifiedBy>Octryx</cp:lastModifiedBy><cp:revision>1</cp:revision>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{_FIXED_DATE}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{_FIXED_DATE}</dcterms:modified>'
        "</cp:coreProperties>"
    )


_TRANSFORMS: dict[str, Callable[[str], str]] = {
    "[Content_Types].xml": lambda xml: xml.replace(
        "presentationml.presentation.main+xml", "presentationml.template.main+xml"
    ),
    "_rels/.rels": lambda xml: _drop_relationships(xml, ("docProps/thumbnail.jpeg",)),
    "ppt/_rels/presentation.xml.rels": lambda xml: _drop_relationships(xml, ("printerSettings1.bin",)),
    "ppt/presentation.xml": _presentation,
    "docProps/core.xml": _core_properties,
    "docProps/app.xml": lambda xml: xml.replace("On-screen Show (4:3)", "Widescreen"),
}


def _transform(name: str, data: bytes) -> bytes:
    transform = _TRANSFORMS.get(name)
    if transform is None and _WIDENED_PARTS.match(name):
        transform = _widen_part
    if transform is None:
        return data
    return transform(data.decode("utf-8")).encode("utf-8")


def build_neutral_presentation_template() -> bytes:
    """The neutral template's bytes, built from the locked python-pptx default template."""
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(_source_bytes())) as source,
        zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            if item.filename in _DROPPED_MEMBERS:
                continue
            member = zipfile.ZipInfo(item.filename, date_time=_FIXED_TIMESTAMP)
            member.compress_type = zipfile.ZIP_DEFLATED
            member.create_system = 3
            member.external_attr = 0o644 << 16
            target.writestr(member, _transform(item.filename, source.read(item.filename)))
    return output.getvalue()


def source_version() -> str:
    """The python-pptx release the tracked file was built from."""
    return metadata.version("python-pptx")


def main() -> None:
    NEUTRAL_TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    NEUTRAL_TEMPLATE_PATH.write_bytes(build_neutral_presentation_template())
    print(f"wrote {NEUTRAL_TEMPLATE_PATH} from python-pptx {source_version()}")


if __name__ == "__main__":
    main()


__all__ = ["NEUTRAL_TEMPLATE_PATH", "build_neutral_presentation_template", "source_version"]
