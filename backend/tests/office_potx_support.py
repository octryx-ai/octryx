"""PowerPoint fixture of the Office tests: a small but parseable generated template (.potx) package."""

from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

LAYOUT_NAMES = [
    "Title Slide",
    "Title and Bulletpoints",
    "Section Header Blue",
    "Title and Subtitle Picture",
    "Statement Title and subtitle",
]


def _relationship_xml(entries: list[tuple[str, str, str]]) -> str:
    rels = "\n".join(
        f'  <Relationship Id="{rel_id}" Type="{rel_type}" Target="{target}"/>' for rel_id, rel_type, target in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        f"{rels}\n"
        "</Relationships>"
    )


def _shape_xml(shape_id: int, name: str, placeholder_type: str, x: int, y: int, cx: int, cy: int) -> str:
    placeholder_attr = f' type="{placeholder_type}"' if placeholder_type else ""
    return f"""
    <p:sp>
      <p:nvSpPr>
        <p:cNvPr id="{shape_id}" name="{name}"/>
        <p:cNvSpPr/>
        <p:nvPr><p:ph{placeholder_attr} idx="{shape_id}"/></p:nvPr>
      </p:nvSpPr>
      <p:spPr>
        <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>
      </p:spPr>
      <p:txBody><a:bodyPr/><a:p><a:r><a:t>{name}</a:t></a:r></a:p></p:txBody>
    </p:sp>"""


def _layout_xml(name: str, *, layout_type: str = "body") -> str:
    body_placeholder = (
        _shape_xml(2, "Picture", "pic", 750_000, 1_250_000, 5_000_000, 2_700_000)
        if layout_type == "picture"
        else _shape_xml(2, "Body", "body", 750_000, 1_250_000, 7_600_000, 2_700_000)
    )
    subtitle = _shape_xml(3, "Subtitle", "subTitle", 750_000, 3_950_000, 7_600_000, 650_000)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             type="obj">
  <p:cSld name="{name}">
    <p:spTree>
      {_shape_xml(1, "Title", "title", 650_000, 350_000, 7_900_000, 650_000)}
      {body_placeholder}
      {subtitle if layout_type in {"subtitle", "picture"} else ""}
    </p:spTree>
  </p:cSld>
</p:sldLayout>"""


def _slide_xml(title: str, body: str, *, include_icon: bool = False) -> str:
    icon_markup = ""
    if include_icon:
        icon_markup = """
    <p:pic>
      <p:nvPicPr><p:cNvPr id="20" name="person.svg"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
      <p:blipFill><a:blip r:embed="rIdIcon"/></p:blipFill>
      <p:spPr>
        <a:xfrm><a:off x="420000" y="220000"/><a:ext cx="250000" cy="250000"/></a:xfrm>
      </p:spPr>
    </p:pic>
    <p:sp>
      <p:nvSpPr><p:cNvPr id="21" name="Icon Label"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr><a:xfrm><a:off x="120000" y="730000"/><a:ext cx="900000" cy="220000"/></a:xfrm></p:spPr>
      <p:txBody><a:bodyPr/><a:p><a:r><a:t>ICO_person</a:t></a:r></a:p></p:txBody>
    </p:sp>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld><p:spTree>
    <p:sp>
      <p:nvSpPr><p:cNvPr id="1" name="Title"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
      <p:spPr><a:xfrm><a:off x="650000" y="350000"/><a:ext cx="7900000" cy="650000"/></a:xfrm></p:spPr>
      <p:txBody><a:bodyPr/><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody>
    </p:sp>
    <p:sp>
      <p:nvSpPr><p:cNvPr id="2" name="Body"/><p:cNvSpPr/><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>
      <p:spPr><a:xfrm><a:off x="750000" y="1250000"/><a:ext cx="7600000" cy="2700000"/></a:xfrm></p:spPr>
      <p:txBody><a:bodyPr/><a:p><a:r><a:t>{body}</a:t></a:r></a:p></p:txBody>
    </p:sp>
    {icon_markup}
  </p:spTree></p:cSld>
</p:sld>"""


_ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""

_THEME_XML = """<?xml version="1.0" encoding="UTF-8"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Test Brand">
  <a:themeElements>
    <a:clrScheme name="Test Brand">
      <a:dk1><a:srgbClr val="111111"/></a:dk1>
      <a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:accent1><a:srgbClr val="2A3F6B"/></a:accent1>
      <a:accent2><a:srgbClr val="00A6A6"/></a:accent2>
      <a:accent3><a:srgbClr val="63C384"/></a:accent3>
    </a:clrScheme>
    <a:fontScheme name="Test Brand Fonts">
      <a:majorFont><a:latin typeface="Aptos Display"/></a:majorFont>
      <a:minorFont><a:latin typeface="Aptos"/></a:minorFont>
    </a:fontScheme>
  </a:themeElements>
</a:theme>"""


def _content_types_xml() -> str:
    layout_overrides = "\n".join(
        (
            f'  <Override PartName="/ppt/slideLayouts/slideLayout{idx}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        )
        for idx in range(1, len(LAYOUT_NAMES) + 1)
    )
    slide_overrides = "\n".join(
        (
            f'  <Override PartName="/ppt/slides/slide{idx}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        )
        for idx in range(1, len(LAYOUT_NAMES) + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
{layout_overrides}
{slide_overrides}
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="svg" ContentType="image/svg+xml"/>
</Types>"""


def _presentation_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldSz cx="9144000" cy="5143500" type="screen16x9" />
  <p:sldIdLst>
    {"".join(f'<p:sldId id="{255 + idx}" r:id="rId{idx}"/>' for idx in range(1, len(LAYOUT_NAMES) + 1))}
  </p:sldIdLst>
</p:presentation>"""


def _write_layouts_and_slides(zf: zipfile.ZipFile) -> None:
    for idx, layout_name in enumerate(LAYOUT_NAMES, start=1):
        layout_type = "picture" if "Picture" in layout_name else "subtitle" if "subtitle" in layout_name else "body"
        zf.writestr(f"ppt/slideLayouts/slideLayout{idx}.xml", _layout_xml(layout_name, layout_type=layout_type))
        zf.writestr(
            f"ppt/slides/slide{idx}.xml",
            _slide_xml(
                "Icons General" if idx == 2 else layout_name,
                "Corporate Identity Guide" if idx == 1 else "How to add slides with branded layouts",
                include_icon=idx == 2,
            ),
        )
        rels = [
            (
                "rIdLayout",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
                f"../slideLayouts/slideLayout{idx}.xml",
            )
        ]
        if idx == 2:
            rels.append(
                (
                    "rIdIcon",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                    "../media/person.svg",
                )
            )
        zf.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", _relationship_xml(rels))


def _build_test_potx(path: Path) -> None:
    """Create a small but parseable PowerPoint template package."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml())
        zf.writestr("_rels/.rels", _ROOT_RELS_XML)
        zf.writestr("ppt/presentation.xml", _presentation_xml())
        zf.writestr(
            "ppt/_rels/presentation.xml.rels",
            _relationship_xml(
                [
                    (
                        f"rId{idx}",
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
                        f"slides/slide{idx}.xml",
                    )
                    for idx in range(1, len(LAYOUT_NAMES) + 1)
                ]
            ),
        )
        zf.writestr("ppt/theme/theme1.xml", _THEME_XML)
        _write_layouts_and_slides(zf)
        zf.writestr("ppt/media/person.svg", "<svg xmlns='http://www.w3.org/2000/svg'><title>person icon</title></svg>")


def _fixture_dir() -> Path:
    """Per process: parallel test workers must not rewrite each other's fixture packages mid-read."""
    root = Path(tempfile.gettempdir()) / "octryx-test-office-fixtures" / str(os.getpid())
    root.mkdir(parents=True, exist_ok=True)
    return root


def office_potx_path(name: str = "Templates-test.potx") -> Path:
    """Return a stable generated test template path."""
    root = _fixture_dir()
    path = root / name
    _build_test_potx(path)
    return path
