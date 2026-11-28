"""Icon-slot filling for the "Icons N Topics" layout family."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from app.services.office_identity.icon_embedding import icon_aspect_ratio
from app.services.office_identity.icon_slots import (
    ICON_TOPICS,
    icon_anchors,
    icon_fit_rect,
    plan_icon_placements,
    select_icon,
)
from app.services.office_identity.template_snapshot import build_template_snapshot
from tests.support.office_template_fixture import write_template

_NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


@pytest.fixture(scope="module")
def library_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_template(tmp_path_factory.mktemp("library") / "library.potx", "library")


@pytest.fixture(scope="module")
def brand_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_template(tmp_path_factory.mktemp("brand") / "brand.potx", "brand")


def _geometry(shape: ET.Element) -> dict[str, int] | None:
    props = shape.find(f"{{{_NS_P}}}spPr")
    if props is None:
        return None
    xfrm = props.find(f"{{{_NS_A}}}xfrm")
    if xfrm is None:
        return None
    off = xfrm.find(f"{{{_NS_A}}}off")
    ext = xfrm.find(f"{{{_NS_A}}}ext")
    return {
        "x_emu": int(off.attrib.get("x", 0)) if off is not None else 0,
        "y_emu": int(off.attrib.get("y", 0)) if off is not None else 0,
        "w_emu": int(ext.attrib.get("cx", 0)) if ext is not None else 0,
        "h_emu": int(ext.attrib.get("cy", 0)) if ext is not None else 0,
    }


def _layout_xml(circles: list[tuple[int, int, int]], *, placeholder: bool = True) -> ET.Element:
    shapes = []
    if placeholder:
        shapes.append(
            f'<p:sp xmlns:p="{_NS_P}" xmlns:a="{_NS_A}"><p:nvSpPr><p:cNvPr id="1" name="Title"/>'
            '<p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
            '<p:spPr><a:xfrm><a:off x="180000" y="195264"/><a:ext cx="8784000" cy="576261"/></a:xfrm>'
            '<a:prstGeom prst="rect"/></p:spPr></p:sp>'
        )
    for index, (x, y, size) in enumerate(circles, start=10):
        shapes.append(
            f'<p:sp xmlns:p="{_NS_P}" xmlns:a="{_NS_A}"><p:nvSpPr><p:cNvPr id="{index}" name="Oval {index}"/>'
            "<p:cNvSpPr/><p:nvPr/></p:nvSpPr>"
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{size}" cy="{size}"/></a:xfrm>'
            '<a:prstGeom prst="ellipse"/><a:solidFill><a:schemeClr val="bg1"/></a:solidFill></p:spPr></p:sp>'
        )
    xml = (
        f'<p:sldLayout xmlns:p="{_NS_P}" xmlns:a="{_NS_A}"><p:cSld><p:spTree>'
        + "".join(shapes)
        + "</p:spTree></p:cSld></p:sldLayout>"
    )
    return ET.fromstring(xml)


_SLIDE_SIZE = {"width_emu": 9144000, "height_emu": 5143500}


def test_icon_anchors_read_the_static_circles_left_to_right():
    root = _layout_xml(
        [(7146613, 1368000, 864000), (1127983, 1368000, 864000), (4140000, 1368000, 864000)]
    )
    anchors = icon_anchors(root, _SLIDE_SIZE, _geometry)
    assert [a["x_emu"] for a in anchors] == [1127983, 4140000, 7146613]
    assert all(a["w_emu"] == 864000 and a["h_emu"] == 864000 for a in anchors)


def test_icon_anchors_ignore_placeholders_and_full_slide_ovals():
    # A slide-filling oval is a decorative panel, not an icon holder.
    root = _layout_xml([(0, 0, 9144000)])
    assert icon_anchors(root, _SLIDE_SIZE, _geometry) == []


def test_icon_anchors_ignore_long_thin_ellipses():
    root = ET.fromstring(
        f'<p:sldLayout xmlns:p="{_NS_P}" xmlns:a="{_NS_A}"><p:cSld><p:spTree>'
        f'<p:sp><p:nvSpPr><p:cNvPr id="9" name="Rule"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="0" y="100"/><a:ext cx="4000000" cy="80000"/></a:xfrm>'
        '<a:prstGeom prst="ellipse"/></p:spPr></p:sp>'
        "</p:spTree></p:cSld></p:sldLayout>"
    )
    assert icon_anchors(root, _SLIDE_SIZE, _geometry) == []


def test_icon_anchors_are_deterministic():
    root = _layout_xml([(4140000, 1368000, 864000), (1127983, 1368000, 864000)])
    assert icon_anchors(root, _SLIDE_SIZE, _geometry) == icon_anchors(root, _SLIDE_SIZE, _geometry)


def _catalog(*slugs: str) -> dict:
    return {"icons": [{"slug": slug, "part": f"ppt/media/{slug}.svg"} for slug in slugs]}


def test_select_icon_takes_the_first_shipped_slug_of_the_topic():
    # network prefers "networks", then "connectivity", then "globe".
    catalog = _catalog("globe", "connectivity")
    icon = select_icon(catalog, "network")
    assert icon is not None and icon["slug"] == "connectivity"


def test_select_icon_is_none_when_the_catalog_ships_no_candidate():
    assert select_icon(_catalog("apple", "car"), "security") is None


def test_select_icon_is_none_for_an_unknown_topic_key():
    assert select_icon(_catalog("shield"), "not-a-topic") is None


def test_select_icon_is_none_without_a_catalog():
    assert select_icon({"icons": []}, "data") is None


def test_select_icon_is_deterministic():
    catalog = _catalog("globe", "connectivity", "networks")
    assert select_icon(catalog, "network")["slug"] == select_icon(catalog, "network")["slug"]
    assert select_icon(catalog, "network")["slug"] == "networks"


def test_icon_topics_reference_only_lowercase_slug_tokens():
    for candidates in ICON_TOPICS.values():
        assert candidates
        assert all(slug == slug.lower() for slug in candidates)


def test_icon_fit_rect_centres_a_square_icon_in_the_circle():
    anchor = {"x_emu": 1000000, "y_emu": 2000000, "w_emu": 864000, "h_emu": 864000}
    rect = icon_fit_rect(anchor, 1.0)
    assert rect["x_emu"] + rect["w_emu"] // 2 == anchor["x_emu"] + anchor["w_emu"] // 2
    assert rect["y_emu"] + rect["h_emu"] // 2 == anchor["y_emu"] + anchor["h_emu"] // 2
    assert rect["x_emu"] >= anchor["x_emu"] and rect["y_emu"] >= anchor["y_emu"]
    assert rect["w_emu"] <= anchor["w_emu"] and rect["h_emu"] <= anchor["h_emu"]


def test_icon_fit_rect_preserves_a_wide_aspect():
    anchor = {"x_emu": 0, "y_emu": 0, "w_emu": 800000, "h_emu": 800000}
    rect = icon_fit_rect(anchor, 2.0)
    assert abs(rect["w_emu"] / rect["h_emu"] - 2.0) < 0.02
    assert rect["w_emu"] <= anchor["w_emu"]


def test_icon_aspect_ratio_reads_the_viewbox():
    assert abs(icon_aspect_ratio(b'<svg viewBox="0 0 500 250"></svg>') - 2.0) < 1e-6
    assert icon_aspect_ratio(b"<svg></svg>") == 1.0
    assert icon_aspect_ratio(b"") == 1.0


def test_corporate_fills_every_icon_holder_from_its_catalog(library_template):
    snapshot = build_template_snapshot(library_template)
    layout = next(layer for layer in snapshot["layouts"] if layer["key"] == "icons-3-topics")
    anchors = layout["icon_anchors"]
    assert len(anchors) == 3

    topics = ["resource_types", "services", "regions"]
    placements, unresolved = plan_icon_placements(layout, topics, snapshot)
    assert unresolved == []
    assert [p["topic_key"] for p in placements] == topics
    for placement in placements:
        rect = icon_fit_rect(placement["anchor"], 1.0)
        anchor = placement["anchor"]
        assert anchor["x_emu"] <= rect["x_emu"]
        assert rect["x_emu"] + rect["w_emu"] <= anchor["x_emu"] + anchor["w_emu"]


def test_template_without_icon_catalog_fills_no_holder(brand_template):
    snapshot = build_template_snapshot(brand_template)
    assert snapshot["icons"] == []
    layout = next(layer for layer in snapshot["layouts"] if layer["key"] == "icons-3-topics")
    assert len(layout["icon_anchors"]) == 3
    placements, unresolved = plan_icon_placements(
        layout, ["resource_types", "services", "regions"], snapshot
    )
    # No catalog -> nothing placed, and every topic reported as unresolved so
    # the composer can raise the ``icons_unavailable`` info finding.
    assert placements == []
    assert set(unresolved) == {"resource_types", "services", "regions"}


import zipfile  # noqa: E402

from app.services.office_identity import build_presentation_from_plan  # noqa: E402

_ICONS_PLAN = [
    {
        "title": "The survey in three numbers",
        "content_shape": "icons_3",
        "icon_topics": ["resource_types", "services", "regions"],
        "blocks": [
            {"heading": "14", "bullets": ["distinct resource types"]},
            {"heading": "5", "bullets": ["AWS services with resources"]},
            {"heading": "2", "bullets": ["Regions"]},
        ],
    }
]


def test_composer_embeds_template_icons_as_svg_parts(tmp_path, library_template):
    template = library_template
    snapshot = build_template_snapshot(template)
    output = tmp_path / "corp-icons.pptx"
    result = build_presentation_from_plan(template, snapshot, _ICONS_PLAN, output)

    placed = [slot for slot in result["filled_slots"] if slot.startswith("icon:")]
    assert len(placed) == 3
    assert not [f for f in result["quality_findings"] if f["code"] == "icons_unavailable"]
    assert not [f for f in result["quality_findings"] if f["severity"] == "warning"]

    with zipfile.ZipFile(output) as archive:
        svgs = [name for name in archive.namelist() if name.startswith("ppt/media/octryx-icon-")]
        assert len(svgs) == 3
        assert all(archive.read(name).lstrip().startswith(b"<svg") for name in svgs)


def test_composer_reports_icons_unavailable_without_a_catalog(tmp_path, brand_template):
    template = brand_template
    snapshot = build_template_snapshot(template)
    output = tmp_path / "brand-icons.pptx"
    result = build_presentation_from_plan(template, snapshot, _ICONS_PLAN, output)

    assert not [slot for slot in result["filled_slots"] if slot.startswith("icon:")]
    unavailable = [f for f in result["quality_findings"] if f["code"] == "icons_unavailable"]
    assert len(unavailable) == 1
    assert unavailable[0]["severity"] == "info"
    with zipfile.ZipFile(output) as archive:
        assert not [n for n in archive.namelist() if n.startswith("ppt/media/octryx-icon-")]
