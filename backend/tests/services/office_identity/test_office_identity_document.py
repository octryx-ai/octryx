"""The Word composer mirrors the deck: template styles, evidence, open points."""

import struct
import zlib
from pathlib import Path

from docx import Document

from app.services.office_identity import (
    build_aws_document_plan,
    build_document_from_plan,
    build_document_snapshot,
)
from app.services.office_identity.document_snapshot import style_for_role


def _png_bytes(width: int = 8, height: int = 8) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _brand_template(path: Path) -> Path:
    Document().save(str(path))
    return path


def _snapshot() -> dict:
    return {
        "account_id": "123456789012",
        "region": "eu-central-1",
        "service_summary": {
            "resource_node_count": 232,
            "edge_count": 444,
            "node_counts_by_type": {"subnet": 9, "load_balancer": 5, "rds_instance": 2, "bedrock_model": 25},
        },
        "scope": {"regions": ["eu-central-1"]},
    }


def test_document_snapshot_maps_roles_to_template_styles(tmp_path):
    snap = build_document_snapshot(_brand_template(tmp_path / "brand.docx"))

    assert snap["kind"] == "office_document_style_snapshot"
    assert style_for_role(snap, "title") == "Title"
    assert style_for_role(snap, "heading1") == "Heading 1"
    assert style_for_role(snap, "body") == "Normal"
    assert snap["summary"]["has_title"] is True
    assert snap["summary"]["heading_depth"] >= 2
    heading = next(s for s in snap["styles"] if s["name"] == "Heading 1")
    assert heading["font"]["bold"] is True
    assert heading["font"]["size_pt"] is not None


def test_missing_template_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        build_document_snapshot(tmp_path / "nope.docx")


def test_snapshot_extracts_theme_and_branding(tmp_path):
    snap = build_document_snapshot(_brand_template(tmp_path / "brand.docx"))

    assert snap["theme"]["fonts"].get("minorFont")
    assert len(snap["theme"]["colors"]) >= 6
    assert all(value.startswith("#") for value in snap["theme"]["colors"].values())
    assert "logo_media" in snap["branding"]
    assert "footer_text" in snap["branding"]
    assert snap["summary"]["brand_color_count"] == len(snap["theme"]["colors"])
    assert "theme_fonts" in snap["summary"]


def test_composer_drops_template_sample_body_keeps_sections(tmp_path):
    # The template ships a sample paragraph and a content control; the composer
    # must drop both while keeping the section (headers/footers) intact.
    template = _brand_template(tmp_path / "brand.docx")
    seeded = Document(str(template))
    seeded.add_paragraph("TEMPLATE SAMPLE CONTENT", style="Normal")
    seeded.save(str(template))

    snap = build_document_snapshot(template)
    plan = build_aws_document_plan(_snapshot(), snap)
    out = tmp_path / "r.docx"
    build_document_from_plan(template, snap, plan, out)

    reopened = Document(str(out))
    texts = [p.text for p in reopened.paragraphs]
    assert "TEMPLATE SAMPLE CONTENT" not in texts
    assert any("AWS architecture" in t for t in texts)
    assert reopened.sections


def test_document_plan_is_evidence_bound_with_open_points():
    snap = {"account_id": "1"}
    plan = build_aws_document_plan(_snapshot(), snap)

    kinds = [b["kind"] for b in plan]
    assert kinds[0] == "title"
    assert "heading" in kinds
    assert kinds[-1] == "marker" or "marker" in kinds
    titled = [b for b in plan if b["kind"] in {"title", "heading"}]
    assert all(b.get("source") for b in titled)
    markers = [b["text"] for b in plan if b["kind"] == "marker"]
    assert any("[DECISION:" in m for m in markers)
    assert any("bedrock_model" in m for m in markers)
    paragraphs = [b["text"] for b in plan if b["kind"] == "paragraph"]
    assert any("232 resources" in p and "444 relationships" in p for p in paragraphs)


def test_composer_writes_with_template_styles_and_embeds_diagram(tmp_path):
    template = _brand_template(tmp_path / "brand.docx")
    snap = build_document_snapshot(template)

    png = tmp_path / "d.png"
    png.write_bytes(_png_bytes())
    plan = build_aws_document_plan(
        _snapshot(), snap, diagram_images=[{"path": str(png), "title": "AWS Topology Overview", "diagram_id": "x"}]
    )
    out = tmp_path / "report.docx"
    result = build_document_from_plan(template, snap, plan, out)

    assert out.is_file()
    assert result["images_embedded"] == 1
    assert not result["quality_findings"]

    reopened = Document(str(out))
    used_styles = {p.style.name for p in reopened.paragraphs}
    assert "Title" in used_styles
    assert any(name.startswith("Heading") for name in used_styles)
    title_para = next(p for p in reopened.paragraphs if p.style.name == "Title")
    assert "AWS architecture" in title_para.text
    assert any(p.text.startswith("Source: ") for p in reopened.paragraphs)


def test_composer_reports_missing_diagram_instead_of_failing(tmp_path):
    template = _brand_template(tmp_path / "brand.docx")
    snap = build_document_snapshot(template)
    plan = build_aws_document_plan(
        _snapshot(), snap, diagram_images=[{"path": "/no/such.png", "title": "Ghost", "diagram_id": "g"}]
    )
    result = build_document_from_plan(template, snap, plan, tmp_path / "r.docx")

    assert result["images_embedded"] == 0
    assert any(f["rule"] == "diagram_missing" for f in result["quality_findings"])
