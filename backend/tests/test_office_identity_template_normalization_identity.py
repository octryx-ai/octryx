"""Package registration, a missing donor, untouched identity and original, the manifest, reproducibility and the synthetic corporate templates of template normalisation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.office_identity.diagram_layout_gaps import DIAGRAM_MIN_AREA_RATIO, find_diagram_full_layout
from app.services.office_identity.layout_authoring import OCTRYX_EXT_URI, LayoutSpec
from app.services.office_identity.layout_registration import add_layouts
from app.services.office_identity.presentation_composer import build_presentation_from_plan
from app.services.office_identity.template_normalization import MANIFEST_NAME, normalize_template
from app.services.office_identity.template_snapshot import build_template_snapshot, layout_by_key
from tests.office_identity_template_normalization_support import (  # noqa: F401
    DERIVED_KEY,
    _picture_slot,
    default_template,
    normalized_default,
)
from tests.office_template_fixture import write_template


@pytest.fixture(scope="module")
def corporate_templates(tmp_path_factory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("corporate-templates")
    return {variant: write_template(root / f"{variant}.potx", variant) for variant in ("brand", "library")}


def test_registration_is_complete_in_the_package(normalized_default):  # noqa: F811
    import zipfile
    from xml.etree import ElementTree as ET

    record = normalized_default["generated_layouts"][0]
    with zipfile.ZipFile(normalized_default["output_path"]) as archive:
        names = set(archive.namelist())
        content_types = archive.read("[Content_Types].xml").decode("utf-8")
        master = archive.read(record["master_part"]).decode("utf-8")
        master_rels = archive.read(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels"
        ).decode("utf-8")
        layout_xml = archive.read(record["part"]).decode("utf-8")

    assert record["part"] in names
    assert "ppt/slideLayouts/_rels/" + Path(record["part"]).name + ".rels" in names
    assert f'PartName="/{record["part"]}"' in content_types
    assert f'Id="{record["relationship_id"]}"' in master_rels
    assert f'id="{record["layout_id"]}"' in master
    assert f'r:id="{record["relationship_id"]}"' in master
    # the marker that makes the catalog able to report the origin
    root = ET.fromstring(layout_xml)
    uris = [
        node.attrib.get("uri")
        for node in root.iter("{http://schemas.openxmlformats.org/presentationml/2006/main}ext")
    ]
    assert OCTRYX_EXT_URI in uris


def test_a_missing_donor_is_an_error_not_a_guess(default_template, tmp_path):  # noqa: F811
    spec = LayoutSpec(
        name="X",
        shape="diagram_full",
        donor_part="ppt/slideLayouts/slideLayout999.xml",
        master_part="ppt/slideMasters/slideMaster1.xml",
        picture_idx=1,
        picture_rect={"x_emu": 0, "y_emu": 0, "w_emu": 100, "h_emu": 100},
        rationale="",
    )
    with pytest.raises(ValueError, match="donor layout part missing"):
        add_layouts(default_template, tmp_path / "broken.pptx", [spec])


# ---------------------------------------------------------------------------
# identity and provenance
# ---------------------------------------------------------------------------


def test_identity_is_untouched(default_template, normalized_default):  # noqa: F811
    before = build_template_snapshot(default_template)
    after = build_template_snapshot(normalized_default["output_path"])
    assert after["theme"] == before["theme"]
    assert after["masters"] == before["masters"]
    assert after["slide_size"] == before["slide_size"]
    assert after["summary"]["master_count"] == before["summary"]["master_count"]
    assert after["summary"]["layout_count"] == before["summary"]["layout_count"] + 1


def test_the_original_is_not_modified(default_template, tmp_path):  # noqa: F811
    before = hashlib.sha256(default_template.read_bytes()).hexdigest()
    normalize_template(default_template, tmp_path / "derived.pptx")
    assert hashlib.sha256(default_template.read_bytes()).hexdigest() == before


def test_the_manifest_explains_every_generated_layout(normalized_default):  # noqa: F811
    manifest = json.loads(Path(normalized_default["manifest_path"]).read_text(encoding="utf-8"))
    assert Path(normalized_default["manifest_path"]).name == MANIFEST_NAME
    assert manifest["source_sha256"] == normalized_default["source_sha256"]
    assert manifest["generated_at"]
    record = manifest["generated_layouts"][0]
    assert record["key"] == DERIVED_KEY
    assert record["cloned_from"].startswith("ppt/slideLayouts/")
    assert record["cloned_from_key"]
    assert set(record["geometry_emu"]) == {"x_emu", "y_emu", "w_emu", "h_emu"}
    assert record["rationale"]


# ---------------------------------------------------------------------------
# reproducibility
# ---------------------------------------------------------------------------


def test_normalisation_is_reproducible(default_template, tmp_path):  # noqa: F811
    first = normalize_template(default_template, tmp_path / "a" / "n.pptx")
    second = normalize_template(default_template, tmp_path / "b" / "n.pptx")
    assert [
        (item["key"], item["geometry_emu"], item["cloned_from"], item["layout_id"])
        for item in first["generated_layouts"]
    ] == [
        (item["key"], item["geometry_emu"], item["cloned_from"], item["layout_id"])
        for item in second["generated_layouts"]
    ]
    assert (
        Path(first["output_path"]).read_bytes() == Path(second["output_path"]).read_bytes()
    ), "the same template must produce a byte-identical derivative"


# ---------------------------------------------------------------------------
# the corporate templates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant", ["brand", "library"], ids=["corp-a", "corp-b"])
def test_corporate_templates_have_the_gap_and_get_it_closed(variant, corporate_templates, tmp_path):
    source = corporate_templates[variant]
    snapshot = build_template_snapshot(source)
    assert find_diagram_full_layout(snapshot) is None, (
        "the reference templates offer no large picture area that spares the brand"
    )
    report = normalize_template(source, tmp_path / "normalized.potx")
    assert report["status"] == "normalized"
    record = report["generated_layouts"][0]
    assert record["key"] == DERIVED_KEY
    assert record["cloned_from_key"] == "content-right-image-left"

    derived_snapshot = build_template_snapshot(report["output_path"])
    layout = layout_by_key(derived_snapshot, DERIVED_KEY)
    slot = _picture_slot(layout)
    assert slot["full_bleed"] is False
    assert slot["slide_area_ratio"] >= DIAGRAM_MIN_AREA_RATIO
    assert find_diagram_full_layout(derived_snapshot)["key"] == DERIVED_KEY
    assert derived_snapshot["theme"] == snapshot["theme"]


def test_a_diagram_slide_on_the_derivative_passes_the_gate(corporate_templates, tmp_path):
    """The point of the whole slice: the composer picks the generated layout by
    name and the gate finds nothing to complain about."""
    source = corporate_templates["brand"]
    report = normalize_template(source, tmp_path / "normalized.potx")
    snapshot = build_template_snapshot(report["output_path"])
    from PIL import Image  # Pillow ships with python-pptx

    image = tmp_path / "diagram.png"
    Image.new("RGB", (1600, 1100), "white").save(image)
    result = build_presentation_from_plan(
        report["output_path"],
        snapshot,
        [
            {
                "title": "AWS Platform Topology",
                "layout_key": DERIVED_KEY,
                "image_slots": [str(image)],
            }
        ],
        tmp_path / "deck.pptx",
    )
    assert result["layout_keys"] == [DERIVED_KEY]
    assert result["quality_findings"] == []
    assert any(entry.startswith("title@") for entry in result["filled_slots"])
    assert any(entry.startswith("picture@") for entry in result["filled_slots"])
