import json
import zipfile
from pathlib import Path

import pytest

from app.services.office.ai_template import build_ai_ready_presentation_template

_LAYOUTS = {
    "Cover Layout": ("ctrTitle", "subTitle"),
    "Picture Layout": ("title", "pic"),
    "Content Layout": ("title", "body"),
}


def _layout_part(name: str, placeholder_types: tuple[str, ...]) -> str:
    shapes = "".join(
        f'<p:sp><p:nvSpPr><p:cNvPr id="{index}" name="{kind}"/><p:cNvSpPr/>'
        f'<p:nvPr><p:ph type="{kind}" idx="{index}"/></p:nvPr></p:nvSpPr></p:sp>'
        for index, kind in enumerate(placeholder_types, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sldLayout xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        f'<p:cSld name="{name}"><p:spTree>{shapes}</p:spTree></p:cSld></p:sldLayout>'
    )


def _write_showcase_like_potx(
    path: Path,
    slide_count: int = 5,
    slide_relationships: dict[int, str] | None = None,
) -> None:
    relationship_overrides = slide_relationships or {}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/ppt/presentation.xml"
            ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml"
            ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml"
            ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
</Types>""",
        )
        zf.writestr(
            "ppt/presentation.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldSz cx="9144000" cy="5143500" type="screen16x9" />
  <p:sldIdLst>
"""
            + "\n".join(f'    <p:sldId id="{256 + index}" r:id="rId{index}"/>' for index in range(1, slide_count + 1))
            + """
  </p:sldIdLst>
</p:presentation>""",
        )
        zf.writestr(
            "ppt/_rels/presentation.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
"""
            + "\n".join(
                (
                    f'  <Relationship Id="rId{index}" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
                    f'Target="slides/slide{index}.xml"/>'
                )
                for index in range(1, slide_count + 1)
            )
            + """
</Relationships>""",
        )
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
                Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
                Target="ppt/presentation.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "ppt/slideMasters/slideMaster1.xml",
            '<p:sldMaster xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
        )
        zf.writestr(
            "ppt/theme/theme1.xml",
            '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Test"/>',
        )
        zf.writestr(
            "docProps/core.xml",
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>',
        )
        zf.writestr(
            "docProps/app.xml",
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"/>',
        )
        for index, (name, placeholder_types) in enumerate(_LAYOUTS.items(), start=1):
            zf.writestr(f"ppt/slideLayouts/slideLayout{index}.xml", _layout_part(name, placeholder_types))
        for index in range(1, slide_count + 1):
            zf.writestr(
                f"ppt/slides/slide{index}.xml",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Slide {index}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>""",
            )
            zf.writestr(
                f"ppt/slides/_rels/slide{index}.xml.rels",
                relationship_overrides.get(
                    index,
                    """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>""",
                ),
            )


def _manifest(extracted_root: Path, slide_count: int) -> None:
    extracted_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "slide_count": slide_count,
        "slides": [{"title": f"Slide {index}", "text_sample": []} for index in range(1, slide_count + 1)],
        "theme_colors": {"accent1": "2A3F6B"},
        "assets": [],
    }
    (extracted_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_build_ai_ready_presentation_template_starts_from_an_empty_deck_on_named_layouts(tmp_path):
    source = tmp_path / "showcase.potx"
    _write_showcase_like_potx(source, slide_count=5)
    _manifest(tmp_path / "extract", 5)

    result = build_ai_ready_presentation_template(
        source_template=source,
        extracted_package_root=tmp_path / "extract",
        output_root=tmp_path / "ai",
        role_definitions=[
            {"role": "title_cover", "layout_name": "Cover Layout", "usage": "Cover", "fields": ["title"]},
            {"role": "content_blocks", "layout_name": "Content Layout", "usage": "Content", "fields": ["body"]},
        ],
    )

    assert Path(result["working_pptx"]).exists()
    assert Path(result["role_matrix_path"]).exists()
    assert Path(result["asset_catalog_path"]).exists()
    assert {item["role"]: item["layout_name"] for item in result["role_matrix"]} == {
        "title_cover": "Cover Layout",
        "content_blocks": "Content Layout",
    }
    with zipfile.ZipFile(result["working_pptx"]) as zf:
        presentation_xml = zf.read("ppt/presentation.xml").decode("utf-8")
        assert not [name for name in zf.namelist() if name.startswith("ppt/slides/")]
    assert "sldId id=" not in presentation_xml
    with zipfile.ZipFile(result["ai_potx"]) as zf:
        content_types = zf.read("[Content_Types].xml").decode("utf-8")
    assert "template.main+xml" in content_types


def test_build_ai_ready_presentation_template_derives_roles_from_the_layout_inventory(tmp_path):
    source = tmp_path / "showcase.potx"
    _write_showcase_like_potx(source, slide_count=1)
    _manifest(tmp_path / "extract", 1)

    result = build_ai_ready_presentation_template(
        source_template=source, extracted_package_root=tmp_path / "extract", output_root=tmp_path / "ai",
    )

    assert [(item["role"], item["layout_name"], item["fields"]) for item in result["role_matrix"]] == [
        ("cover_layout", "Cover Layout", ["subtitle", "title"]),
        ("picture_layout", "Picture Layout", ["image", "title"]),
        ("content_layout", "Content Layout", ["body", "title"]),
    ]


def test_build_ai_ready_presentation_template_requires_a_layout_per_role(tmp_path):
    source = tmp_path / "showcase.potx"
    _write_showcase_like_potx(source, slide_count=1)
    _manifest(tmp_path / "extract", 1)

    with pytest.raises(ValueError, match="without a layout_name: title_cover"):
        build_ai_ready_presentation_template(
            source_template=source, extracted_package_root=tmp_path / "extract", output_root=tmp_path / "ai",
            role_definitions=[{"role": "title_cover", "slide_number": 1}],
        )


def test_build_ai_template_enriches_assets_from_source_slide_media(tmp_path):
    source = tmp_path / "showcase.potx"
    media_dir = tmp_path / "extract" / "assets" / "media"
    media_dir.mkdir(parents=True)
    asset_path = media_dir / "mockup-device.svg"
    asset_path.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 400'><title>mobile device mockup</title></svg>",
        encoding="utf-8",
    )

    _write_showcase_like_potx(
        source,
        slide_count=2,
        slide_relationships={
            2: """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
                Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
                Target="../media/mockup-device.svg"/>
</Relationships>""",
        },
    )

    with zipfile.ZipFile(source, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ppt/media/mockup-device.svg", asset_path.read_text(encoding="utf-8"))

    extracted_root = tmp_path / "extract"
    manifest = {
        "slide_count": 2,
        "slides": [
            {"title": "Cover", "text_sample": ["Cover"]},
            {"title": "Mockup", "text_sample": ["Mockup"]},
        ],
        "theme_colors": {"accent1": "2A3F6B"},
        "assets": [
            {
                "category": "vector",
                "path": str(asset_path),
                "file_name": "mockup-device.svg",
                "source": "ppt/media/mockup-device.svg",
                "suffix": ".svg",
                "size_bytes": asset_path.stat().st_size,
            }
        ],
    }
    (extracted_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = build_ai_ready_presentation_template(
        source_template=source,
        extracted_package_root=extracted_root,
        output_root=tmp_path / "ai",
        role_definitions=[
            {
                "role": "image_device_mockup",
                "layout_name": "Picture Layout",
                "source_slide_number": 2,
                "usage": "Mockup",
                "fields": ["title", "image"],
                "placeholder_bindings": {"image": "picture"},
            }
        ],
    )

    asset_catalog = json.loads(Path(result["asset_catalog_path"]).read_text(encoding="utf-8"))
    vector_assets = asset_catalog["vector_assets"]
    assert vector_assets
    assert "image_device_mockup" in vector_assets[0]["preferred_roles"]
    assert "device" in vector_assets[0]["tags"]
