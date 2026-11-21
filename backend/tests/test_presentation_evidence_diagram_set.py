"""The deck embeds the full evidence-diagram set, not one diagram per model draw.

A run that called create_diagram once left a deck with a single diagram slide;
the service inventory and per-tier detail views were never rendered. The deck's
diagrams are now derived deterministically from the snapshot — overview first,
then the inventory and substantive detail views — independent of how many times
the model drew.
"""

from pathlib import Path

import pytest

from app.tools.presentation_impl import _presentation_diagrams as ev


def _node(ref, type_, label, **attrs):
    node = {"ref": ref, "type": type_, "label": label, "service": attrs.pop("service", type_), "region": "eu-central-1"}
    node.update(attrs)
    return node


def _brief_snapshot():
    """A snapshot whose diagram_brief carries enough to build several diagrams."""
    nodes = [
        _node("n1", "aws_account", "123456789012", service="sts"),
        _node("n2", "vpc", "vpc-abc", name="main", attributes={"cidr_block": "10.0.0.0/16"}),
        _node("n3", "subnet", "subnet-pub-a", attributes={"tier": "public", "az": "eu-central-1a"}),
        _node("n4", "subnet", "subnet-priv-a", attributes={"tier": "private", "az": "eu-central-1a"}),
        _node("n5", "subnet", "subnet-db-a", attributes={"tier": "db", "az": "eu-central-1a"}),
        _node("n6", "load_balancer", "alb-0", attributes={"scheme": "internet-facing"}),
        _node("n7", "rds_instance", "rds-0"),
        _node("n8", "rds_instance", "rds-1"),
        _node("n9", "rds_proxy", "rds-proxy-0"),
        _node("n10", "eks_cluster", "eks-0"),
        _node("n11", "dynamodb_table", "ddb-0"),
        _node("n12", "s3_bucket", "s3-0"),
        _node("n13", "sqs_queue", "sqs-0"),
        _node("n14", "internet_gateway", "igw-0"),
        _node("n15", "route_table", "rt-0"),
        _node("n16", "security_group", "sg-0"),
    ]
    edges = [
        {"source_ref": "n3", "target_ref": "n2", "type": "belongs_to"},
        {"source_ref": "n4", "target_ref": "n2", "type": "belongs_to"},
        {"source_ref": "n5", "target_ref": "n2", "type": "belongs_to"},
        {"source_ref": "n6", "target_ref": "n3", "type": "uses_subnet"},
        {"source_ref": "n7", "target_ref": "n5", "type": "uses_subnet"},
        {"source_ref": "n8", "target_ref": "n5", "type": "uses_subnet"},
        {"source_ref": "n10", "target_ref": "n4", "type": "runs_in"},
        {"source_ref": "n6", "target_ref": "n10", "type": "serves"},
        {"source_ref": "n9", "target_ref": "n7", "type": "routes_to"},
        {"source_ref": "n16", "target_ref": "n6", "type": "allows_ingress_to"},
    ]
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "service_summary": {"resource_node_count": len(nodes), "edge_count": len(edges)},
        "scope": {"regions": ["eu-central-1"]},
        "diagram_brief": {"selected_nodes": nodes, "selected_edges": edges},
    }


@pytest.mark.asyncio
async def test_evidence_set_renders_multiple_wrapped_diagrams(tmp_path, monkeypatch):
    rendered: list[tuple[str, str]] = []

    def _fake_render(*, diagram_id: str, diagram_xml: str, scale: int) -> bytes:
        rendered.append((diagram_id, diagram_xml))
        return b"\x89PNG\r\n\x1a\nfake"

    monkeypatch.setattr("app.services.diagram_export_service.render_diagram_png", _fake_render)

    images, warnings = await ev.evidence_diagram_images(
        _brief_snapshot(), output_dir=Path(tmp_path), max_images=4
    )

    # More than one diagram — overview plus at least the service inventory.
    assert len(images) >= 2
    titles = [img["title"] for img in images]
    assert "AWS Topology Overview" in titles
    assert any("inventory" in t.lower() for t in titles)
    # Every diagram was wrapped into a full document before rendering.
    assert all(x.lstrip().startswith("<mxGraphModel") for _id, x in rendered)
    # Stable, unique ids and existing files.
    assert len({img["diagram_id"] for img in images}) == len(images)
    assert all(Path(img["path"]).exists() for img in images)


@pytest.mark.asyncio
async def test_max_images_caps_the_set(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.diagram_export_service.render_diagram_png",
        lambda **_: b"\x89PNG\r\n\x1a\nfake",
    )
    images, warnings = await ev.evidence_diagram_images(
        _brief_snapshot(), output_dir=Path(tmp_path), max_images=2
    )
    assert len(images) == 2
    assert any("omitted" in w for w in warnings)


@pytest.mark.asyncio
async def test_no_diagram_brief_yields_nothing(tmp_path):
    # Without a brief the caller falls back to the turn's own diagrams.
    images, warnings = await ev.evidence_diagram_images(
        {"account_id": "1", "service_summary": {"resource_node_count": 3}},
        output_dir=Path(tmp_path),
        max_images=4,
    )
    assert images == []
    assert warnings == []


def test_evidence_calls_are_bare_cells_needing_a_wrapper():
    calls = ev._evidence_diagram_calls(_brief_snapshot())
    assert calls, "expected at least the overview + inventory calls"
    import json

    xml = json.loads(calls[0]["function"]["arguments"])["xml"]
    # Builders emit bare mxCell elements; the module wraps them before rendering.
    assert not xml.lstrip().startswith("<mxGraphModel")
    assert "<mxCell" in xml
