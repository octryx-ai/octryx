"""Two-upload: a separate example deck teaches layout usage, matched by name."""

import zipfile
from pathlib import Path

from app.services.office_identity.layout_usage import (
    USAGE_SOURCE,
    USAGE_SOURCE_EXAMPLE,
)
from app.services.office_identity.template_snapshot import build_template_snapshot
from tests.support.office_potx_support import _layout_xml, _relationship_xml, _slide_xml

BRAND_LAYOUTS = ["Title Slide", "Title and Bulletpoints", "Statement Title and subtitle"]
EXAMPLE_LAYOUT = "Title and Bulletpoints"
EXAMPLE_SLIDES = 4


SLIDE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
SLIDE_LAYOUT_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
SLIDE_MASTER_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
PACKAGE_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
    "</Relationships>"
)
BRAND_THEME_XML = (
    '<?xml version="1.0"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Brand">'
    '<a:themeElements><a:clrScheme name="Brand"><a:dk1><a:srgbClr val="111111"/></a:dk1>'
    '<a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:accent1><a:srgbClr val="2A3F6B"/></a:accent1></a:clrScheme>'
    '<a:fontScheme name="Brand"><a:majorFont><a:latin typeface="Arial"/></a:majorFont>'
    '<a:minorFont><a:latin typeface="Arial"/></a:minorFont></a:fontScheme></a:themeElements></a:theme>'
)
EXAMPLE_THEME_XML = (
    '<?xml version="1.0"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Other Brand"/>'
)


def _brand_content_types_xml(n: int) -> str:
    layout_ovr = "\n".join(
        f'  <Override PartName="/ppt/slideLayouts/slideLayout{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        for i in range(1, n + 1)
    )
    slide_ovr = "\n".join(
        f'  <Override PartName="/ppt/slides/slide{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, n + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
{layout_ovr}
{slide_ovr}
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
</Types>"""


def _brand_presentation_xml(n: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldSz cx="9144000" cy="5143500" type="screen16x9" />
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rIdMaster"/></p:sldMasterIdLst>
  <p:sldIdLst>
    {"".join(f'<p:sldId id="{255 + i}" r:id="rIdS{i}"/>' for i in range(1, n + 1))}
  </p:sldIdLst>
</p:presentation>"""


def _brand_master_xml(n: int) -> str:
    return (
        '<?xml version="1.0"?>'
        '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<p:cSld><p:spTree/></p:cSld>"
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
        'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        "<p:sldLayoutIdLst>"
        + "".join(f'<p:sldLayoutId id="{2147483649 + i}" r:id="rIdL{i}"/>' for i in range(1, n + 1))
        + "</p:sldLayoutIdLst></p:sldMaster>"
    )


def _write_brand_layout_and_slide(zf: zipfile.ZipFile, i: int, layout_name: str) -> None:
    zf.writestr(f"ppt/slideLayouts/slideLayout{i}.xml", _layout_xml(layout_name, layout_type="body"))
    zf.writestr(
        f"ppt/slideLayouts/_rels/slideLayout{i}.xml.rels",
        _relationship_xml([("rIdMaster", SLIDE_MASTER_REL_TYPE, "../slideMasters/slideMaster1.xml")]),
    )
    zf.writestr(f"ppt/slides/slide{i}.xml", _slide_xml(f"Brand {layout_name}", "One line"))
    zf.writestr(
        f"ppt/slides/_rels/slide{i}.xml.rels",
        _relationship_xml([("rIdLayout", SLIDE_LAYOUT_REL_TYPE, f"../slideLayouts/slideLayout{i}.xml")]),
    )


def _build_brand_template(path: Path, layout_names: list[str]) -> None:
    n = len(layout_names)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _brand_content_types_xml(n))
        zf.writestr("_rels/.rels", PACKAGE_RELS_XML)
        zf.writestr("ppt/presentation.xml", _brand_presentation_xml(n))
        zf.writestr(
            "ppt/_rels/presentation.xml.rels",
            _relationship_xml(
                [("rIdMaster", SLIDE_MASTER_REL_TYPE, "slideMasters/slideMaster1.xml")]
                + [(f"rIdS{i}", SLIDE_REL_TYPE, f"slides/slide{i}.xml") for i in range(1, n + 1)]
            ),
        )
        zf.writestr("ppt/theme/theme1.xml", BRAND_THEME_XML)
        zf.writestr("ppt/slideMasters/slideMaster1.xml", _brand_master_xml(n))
        zf.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            _relationship_xml(
                [("rIdTheme", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme", "../theme/theme1.xml")]
                + [(f"rIdL{i}", SLIDE_LAYOUT_REL_TYPE, f"../slideLayouts/slideLayout{i}.xml") for i in range(1, n + 1)]
            ),
        )
        for i, layout_name in enumerate(layout_names, start=1):
            _write_brand_layout_and_slide(zf, i, layout_name)


def _example_content_types_xml(slide_count: int) -> str:
    slide_overrides = "\n".join(
        f'  <Override PartName="/ppt/slides/slide{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
{slide_overrides}
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
</Types>"""


def _example_presentation_xml(slide_count: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldSz cx="9144000" cy="5143500" type="screen16x9" />
  <p:sldIdLst>
    {"".join(f'<p:sldId id="{255 + i}" r:id="rId{i}"/>' for i in range(1, slide_count + 1))}
  </p:sldIdLst>
</p:presentation>"""


def _build_example_deck(path: Path, *, layout_name: str, slide_count: int) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _example_content_types_xml(slide_count))
        zf.writestr("_rels/.rels", PACKAGE_RELS_XML)
        zf.writestr("ppt/presentation.xml", _example_presentation_xml(slide_count))
        zf.writestr(
            "ppt/_rels/presentation.xml.rels",
            _relationship_xml(
                [(f"rId{i}", SLIDE_REL_TYPE, f"slides/slide{i}.xml") for i in range(1, slide_count + 1)]
            ),
        )
        zf.writestr("ppt/theme/theme1.xml", EXAMPLE_THEME_XML)
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", _layout_xml(layout_name, layout_type="body"))
        for i in range(1, slide_count + 1):
            zf.writestr(f"ppt/slides/slide{i}.xml", _slide_xml(f"Headline {i}", f"Point A {i}\nPoint B {i}\nPoint C {i}"))
            zf.writestr(
                f"ppt/slides/_rels/slide{i}.xml.rels",
                _relationship_xml([("rIdLayout", SLIDE_LAYOUT_REL_TYPE, "../slideLayouts/slideLayout1.xml")]),
            )


def test_no_example_deck_keeps_sample_slide_source(tmp_path):
    template = tmp_path / "brand.potx"
    _build_brand_template(template, BRAND_LAYOUTS)

    snapshot = build_template_snapshot(template)

    assert snapshot["usage_source"] == USAGE_SOURCE
    assert "example_deck" not in snapshot


def test_example_deck_drives_layout_usage(tmp_path):
    template = tmp_path / "brand.potx"
    _build_brand_template(template, BRAND_LAYOUTS)
    example = tmp_path / "example.pptx"
    _build_example_deck(example, layout_name=EXAMPLE_LAYOUT, slide_count=EXAMPLE_SLIDES)

    snapshot = build_template_snapshot(template, example_deck_path=example)

    assert snapshot["usage_source"] == USAGE_SOURCE_EXAMPLE
    assert snapshot["example_deck"]["source_file"] == "example.pptx"
    assert snapshot["example_deck"]["slides"] == EXAMPLE_SLIDES
    assert snapshot["example_deck"]["layouts_learned"] >= 1

    matched = next(
        layout
        for layout in snapshot["layouts"]
        if layout.get("name") == EXAMPLE_LAYOUT and layout.get("usage")
    )
    assert matched["usage"]["usage_source"] == USAGE_SOURCE_EXAMPLE
    assert matched["usage"]["sample_count"] == EXAMPLE_SLIDES

    plain = build_template_snapshot(template)
    assert snapshot["theme"] == plain["theme"]
    assert [layout["key"] for layout in snapshot["layouts"]] == [
        layout["key"] for layout in plain["layouts"]
    ]


def test_example_layout_absent_from_brand_contributes_nothing(tmp_path):
    template = tmp_path / "brand.potx"
    _build_brand_template(template, BRAND_LAYOUTS)
    example = tmp_path / "example.pptx"
    _build_example_deck(example, layout_name="A Layout The Brand Lacks", slide_count=EXAMPLE_SLIDES)

    snapshot = build_template_snapshot(template, example_deck_path=example)

    assert snapshot["example_deck"]["layouts_learned"] == 0
    assert all(
        (layout.get("usage") or {}).get("usage_source") != USAGE_SOURCE_EXAMPLE
        for layout in snapshot["layouts"]
    )


def test_missing_example_deck_is_a_warning_not_a_failure(tmp_path):
    template = tmp_path / "brand.potx"
    _build_brand_template(template, BRAND_LAYOUTS)

    snapshot = build_template_snapshot(template, example_deck_path=tmp_path / "absent.pptx")

    assert snapshot["usage_source"] == USAGE_SOURCE
    assert "example_deck" not in snapshot
    assert any("example deck not found" in w for w in snapshot["warnings"])
