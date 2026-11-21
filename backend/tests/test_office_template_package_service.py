import json
import zipfile
from pathlib import Path

from app.services.office.template_package import extract_office_template_package


def _build_minimal_potx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "ppt/presentation.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldSz cx="9144000" cy="5143500" type="screen16x9" />
</p:presentation>""",
        )
        zf.writestr(
            "ppt/theme/theme1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <a:themeElements>
    <a:clrScheme name="Custom">
      <a:dk1><a:srgbClr val="000000" /></a:dk1>
      <a:lt1><a:srgbClr val="FFFFFF" /></a:lt1>
      <a:accent1><a:srgbClr val="2A3F6B" /></a:accent1>
    </a:clrScheme>
  </a:themeElements>
</a:theme>""",
        )
        zf.writestr(
            "ppt/slideLayouts/slideLayout1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:nvSpPr><p:nvPr><p:ph type="title" /></p:nvPr></p:nvSpPr>
      </p:sp>
      <p:sp>
        <p:nvSpPr><p:nvPr><p:ph type="body" idx="1" /></p:nvPr></p:nvSpPr>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sldLayout>""",
        )
        zf.writestr(
            "ppt/slides/slide1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:txBody><a:p><a:r><a:t>Corporate Title</a:t></a:r></a:p></p:txBody>
      </p:sp>
      <p:sp>
        <p:txBody><a:p><a:r><a:t>Brand subtitle</a:t></a:r></a:p></p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>""",
        )
        zf.writestr("ppt/media/image1.svg", "<svg xmlns='http://www.w3.org/2000/svg'></svg>")
        zf.writestr("ppt/media/image2.png", b"png")


def _build_icon_catalog_potx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "ppt/presentation.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldSz cx="9144000" cy="5143500" type="screen16x9" />
</p:presentation>""",
        )
        zf.writestr(
            "ppt/slides/slide1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:nvSpPr><p:nvPr><p:ph type="title" /></p:nvPr></p:nvSpPr>
        <p:txBody><a:p><a:r><a:t>Icons General</a:t></a:r></a:p></p:txBody>
      </p:sp>
      <p:pic>
        <p:blipFill>
          <a:blip r:embed="rId1">
            <a:extLst>
              <a:ext uri="{96DAC541-7B7A-43D3-8B79-37D633B846F1}">
                <asvg:svgBlip r:embed="rId1" />
              </a:ext>
            </a:extLst>
          </a:blip>
        </p:blipFill>
        <p:spPr>
          <a:xfrm><a:off x="500000" y="500000" /></a:xfrm>
        </p:spPr>
      </p:pic>
      <p:sp>
        <p:txBody><a:p><a:r><a:t>ICO_person</a:t></a:r></a:p></p:txBody>
        <p:spPr>
          <a:xfrm><a:off x="200000" y="900000" /></a:xfrm>
        </p:spPr>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>""",
        )
        zf.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/person.svg"/>
</Relationships>""",
        )
        zf.writestr("ppt/media/person.svg", "<svg xmlns='http://www.w3.org/2000/svg'><title>person</title></svg>")


def _build_multi_slide_potx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "ppt/presentation.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldSz cx="9144000" cy="5143500" type="screen16x9" />
</p:presentation>""",
        )
        zf.writestr(
            "ppt/theme/theme1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <a:themeElements>
    <a:clrScheme name="Custom">
      <a:accent1><a:srgbClr val="2A3F6B" /></a:accent1>
    </a:clrScheme>
  </a:themeElements>
</a:theme>""",
        )
        for layout in (2, 10):
            zf.writestr(
                f"ppt/slideLayouts/slideLayout{layout}.xml",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:nvSpPr><p:nvPr><p:ph type="title" idx="{layout}" /></p:nvPr></p:nvSpPr>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sldLayout>""",
            )
        for slide in (2, 10):
            zf.writestr(
                f"ppt/slides/slide{slide}.xml",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:txBody><a:p><a:r><a:t>Slide {slide}</a:t></a:r></a:p></p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>""",
            )


def test_extract_office_template_package_exports_manifest_and_assets(tmp_path):
    template = tmp_path / "Corporate-Template.potx"
    _build_minimal_potx(template)

    manifest = extract_office_template_package(template, tmp_path / "packages")

    package_root = Path(manifest["package_root"])
    assert package_root.exists()
    assert manifest["doc_type"] == "pptx"
    assert manifest["layout_count"] == 1
    assert manifest["slide_count"] == 1
    assert manifest["vector_asset_count"] == 1
    assert manifest["raster_asset_count"] == 1
    assert manifest["theme_colors"]["accent1"] == "2A3F6B"
    assert manifest["slides"][0]["title"] == "Corporate Title"

    manifest_file = package_root / "manifest.json"
    readme_file = package_root / "README.md"
    assert manifest_file.exists()
    assert readme_file.exists()

    stored = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert stored["template_name"] == "Corporate-Template"
    assert (package_root / "assets" / "media" / "image1.svg").exists()
    assert (package_root / "assets" / "media" / "image2.png").exists()
    svg_asset = next(item for item in stored["assets"] if item["file_name"] == "image1.svg")
    assert "vector" in svg_asset["tags"]
    assert "overview_hero" in svg_asset["preferred_roles"]


def test_extract_office_template_package_sorts_slides_and_layouts_numerically(tmp_path):
    template = tmp_path / "Numeric-Order.potx"
    _build_multi_slide_potx(template)

    manifest = extract_office_template_package(template, tmp_path / "packages")

    assert [item["title"] for item in manifest["slides"]] == ["Slide 2", "Slide 10"]
    assert [item["layout_xml"] for item in manifest["layouts"]] == [
        "ppt/slideLayouts/slideLayout2.xml",
        "ppt/slideLayouts/slideLayout10.xml",
    ]


def test_extract_office_template_package_builds_named_icon_catalog(tmp_path):
    template = tmp_path / "Icon-Template.potx"
    _build_icon_catalog_potx(template)

    manifest = extract_office_template_package(template, tmp_path / "packages")

    assert manifest["icon_count"] == 1
    assert "General" in manifest["icon_categories"]
    catalog_path = Path(manifest["icon_catalog_path"])
    assert catalog_path.exists()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog["total_icons"] == 1
    assert catalog["categories"]["General"][0]["slug"] == "person"
    named_icon = next(item for item in manifest["assets"] if item["file_name"] == "person.svg")
    assert named_icon["icon_slug"] == "person"
    assert "icon" in named_icon["tags"]
