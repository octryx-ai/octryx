"""Deterministic post-render quality gate for AWS diagrams."""

import json

from app.services.diagrams.aws_diagram_quality_gate import (
    apply_quality_gate,
    check_diagram_quality,
)
from app.services.diagrams.aws_topology_diagram import (
    build_aws_topology_diagram_tool_call,
)
from tests.aws_topology_structural_layout_support import (
    _contract,
    _multi_region_topology,
    _shape_library,
    _topology_result,
)


def _cell(cell_id: str, parent: str, x: int, y: int, w: int, h: int) -> str:
    return (
        f'<mxCell id="{cell_id}" vertex="1" parent="{parent}">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
    )


def test_gate_passes_on_rendered_overview_and_multi_region():
    for topology in (_topology_result(), _multi_region_topology()):
        planned = build_aws_topology_diagram_tool_call(
            _contract(), topology, _shape_library(), {"create_diagram"}
        )
        xml = json.loads(planned[0]["function"]["arguments"])["xml"]
        assert "quality_gate_warning" not in xml
        assert check_diagram_quality(xml) == []


def test_gate_flags_overlapping_siblings():
    xml = _cell("a", "1", 0, 0, 100, 100) + _cell("b", "1", 50, 50, 100, 100)
    violations = check_diagram_quality(xml)
    assert any("overlaps" in violation for violation in violations)
    stamped = apply_quality_gate(xml)
    assert "quality_gate_warning" in stamped
    assert "QUALITY GATE" in stamped


def test_gate_flags_children_outside_container():
    xml = _cell("box", "1", 0, 100, 200, 200) + _cell("child", "box", 150, 20, 120, 60)
    violations = check_diagram_quality(xml)
    assert any("exceeds the bounds" in violation for violation in violations)


def test_gate_flags_overcrowded_container():
    cells = [_cell("box", "1", 0, 0, 5000, 5000)]
    cells.extend(
        _cell(f"n{i}", "box", (i % 40) * 120, (i // 40) * 120, 100, 100) for i in range(45)
    )
    violations = check_diagram_quality("".join(cells))
    assert any("holds 45 nodes" in violation for violation in violations)


def test_gate_flags_excessive_edge_density():
    xml = _cell("a", "1", 0, 0, 100, 100) + _cell("b", "1", 200, 0, 100, 100)
    xml += "".join(
        f'<mxCell id="e{i}" edge="1" parent="1" source="a" target="b">'
        '<mxGeometry relative="1" as="geometry"/></mxCell>'
        for i in range(8)
    )
    violations = check_diagram_quality(xml)
    assert any("edge density" in violation for violation in violations)


def test_gate_leaves_clean_xml_unchanged():
    xml = _cell("a", "1", 0, 0, 100, 100) + _cell("b", "1", 200, 0, 100, 100)
    assert apply_quality_gate(xml) == xml


def test_gate_ignores_decorative_overlays_but_flags_solid_overlap():
    # sequence lifelines / invisible anchors / frames overlap solid nodes BY
    # DESIGN (live finding: every auth_flow sequence render got stamped)
    lifeline = (
        '<mxCell id="ll" style="shape=line;strokeColor=#999999;dashed=1;" vertex="1" parent="1">'
        '<mxGeometry x="65" y="130" width="1" height="400" as="geometry"/></mxCell>'
    )
    anchor = (
        '<mxCell id="an" style="ellipse;fillOpacity=0;strokeOpacity=0;" vertex="1" parent="1">'
        '<mxGeometry x="60" y="200" width="6" height="6" as="geometry"/></mxCell>'
    )
    activation = (
        '<mxCell id="act" style="rounded=0;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">'
        '<mxGeometry x="59" y="150" width="12" height="120" as="geometry"/></mxCell>'
    )
    assert check_diagram_quality(lifeline + anchor + activation) == []
    # solid nodes overlapping still stamp
    solid = _cell("a", "1", 0, 0, 100, 100) + _cell("b", "1", 50, 50, 100, 100)
    assert any("overlaps" in violation for violation in check_diagram_quality(solid))
