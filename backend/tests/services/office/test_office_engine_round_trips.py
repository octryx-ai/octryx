"""The Office engine per family: create → read → modify → validate, charts, and style-keeping template fill."""

from __future__ import annotations

import ast
import subprocess
import zipfile
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pptx.util import Pt

from app.services.office.engine import api
from tests.support.office_template_support import write_excel_template, write_word_template

REPO_ROOT = Path(__file__).resolve().parents[4]
ENGINE_DIR = REPO_ROOT / "backend" / "app" / "services" / "office" / "engine"


def _data(result: dict) -> dict:
    assert result.get("success") is True, result
    return result["data"]


def test_word_round_trip(tmp_path):
    path = tmp_path / "report.docx"
    _data(api.create(path))
    _data(api.add(path, "/body", "heading", {"text": "Summary", "level": 1}))
    _data(api.add(path, "/body", "paragraph", {"text": "Draft"}))
    _data(api.add(path, "/body", "table", {"headers": ["Item", "Cost"], "rows": [["Hosting", "800"]]}))
    _data(api.add(path, "/body", "chart", {"chartType": "column", "categories": "Q1,Q2", "series1": "Cost:5,7"}))

    elements = _data(api.view(path, "text"))["elements"]
    assert [item["type"] for item in elements][:3] == ["heading", "paragraph", "table"]

    _data(api.set_properties(path, "/body/p[2]", {"text": "Final", "bold": True}))
    _data(api.set_properties(path, "/body/tbl[1]/tr[2]/tc[2]", {"text": "900"}))
    assert _data(api.get(path, "/body/p[2]", 2))["children"][0]["bold"] is True
    assert _data(api.query(path, "cell:contains(900)"))["count"] == 1
    _data(api.remove(path, "/body/p[2]"))

    validation = _data(api.validate(path))
    assert validation["valid"] is True and validation["issue_count"] == 0
    reopened = Document(str(path))
    assert [p.text for p in reopened.paragraphs][0] == "Summary" and "Final" not in [p.text for p in reopened.paragraphs]
    assert any(str(part.partname).startswith("/word/charts/") for part in reopened.part.package.iter_parts())


def test_powerpoint_round_trip(tmp_path):
    path = tmp_path / "deck.pptx"
    _data(api.create(path))
    _data(api.add(path, "/", "slide", {"layout": "Title Slide", "title": "Kick-off"}))
    second = _data(api.add(path, "/", "slide", {"layout": "Title Only", "title": "Plan"}))["path"]
    shape = _data(api.add(path, second, "shape", {"preset": "roundRect", "text": "Step 1", "fill": "0F4C81"}))["path"]
    _data(api.add(path, second, "table", {"headers": ["Owner", "Due"], "rows": [["Ops", "Q4"]]}))
    _data(api.add(path, second, "chart", {"chart_type": "line", "categories": ["Q1", "Q2"],
                                          "series": [{"name": "Users", "values": [3, 5]}]}))

    slides = _data(api.view(path, "text"))["slides"]
    assert slides[1]["texts"][:2] == ["Plan", "Step 1"]

    _data(api.set_properties(path, shape, {"text": "Step 1\nStep 2", "size": "18", "x": "2cm"}))
    cloned = _data(api.add(path, "/", "slide", {}, from_path=second))["path"]
    assert cloned == "/slide[3]"
    _data(api.remove(path, "/slide[1]"))

    outline = _data(api.view(path, "outline"))
    assert outline["totalSlides"] == 2 and outline["slides"][1]["charts"] == 1 and outline["slides"][1]["tables"] == 1
    assert _data(api.validate(path))["valid"] is True
    deck = Presentation(str(path))
    step = next(s for s in deck.slides[1].shapes if s.has_text_frame and s.text_frame.text.startswith("Step 1"))
    assert step.text_frame.text == "Step 1\nStep 2" and step.text_frame.paragraphs[0].runs[0].font.size == Pt(18)


def test_excel_round_trip_with_a_chart(tmp_path):
    path = tmp_path / "budget.xlsx"
    _data(api.create(path))
    _data(api.set_properties(path, "/Sheet/A1:B3", {"values": [["Month", "Cost"], ["Jan", "10"], ["Feb", "12"]]}))
    chart = _data(api.add(path, "/Sheet", "chart", {"chartType": "column", "dataRange": "Sheet!A1:B3", "title": "Cost"}))
    assert chart["path"] == "/Sheet/chart[1]"

    assert _data(api.get(path, "Sheet!B2"))["value"] == 10
    _data(api.set_properties(path, "/Sheet/B4", {"formula": "=SUM(B2:B3)", "bold": True}))
    _data(api.set_properties(path, "/Sheet/B3", {"value": 15}))
    assert _data(api.get(path, "/Sheet/chart[1]"))["title"] == "Cost"
    assert _data(api.view(path, "stats"))["charts"] == 1

    assert _data(api.validate(path))["valid"] is True
    _data(api.set_properties(path, "/Sheet/C1", {"formula": "=Missing!A1"}))
    broken = _data(api.validate(path))
    assert broken["valid"] is False and broken["issues"][0]["code"] == "unknown_sheet_reference"
    workbook = load_workbook(path)
    assert len(workbook["Sheet"]._charts) == 1 and workbook["Sheet"]["B3"].value == 15


def test_template_fill_keeps_the_template_styles(tmp_path):
    word = api.merge(write_word_template(tmp_path / "brand.dotx"), tmp_path / "letter.docx",
                     {"title": "Offer", "customer": {"name": "ACME"}, "date": "today", "total": 42, "company": "OCX"})
    assert _data(word)["replaced"] == 5 and _data(word)["converted_from_template"] is True
    document = Document(str(tmp_path / "letter.docx"))
    lead = next(p for p in document.paragraphs if p.text.startswith("Prepared for"))
    assert lead.text == "Prepared for ACME on today"
    assert lead.runs[0].bold is True and lead.runs[0].font.size == Pt(14) and str(lead.runs[0].font.color.rgb) == "2A3F6B"
    assert document.paragraphs[0].style.name == "Heading 1" and document.paragraphs[0].text == "Offer"
    assert document.tables[0].cell(0, 1).text == "42" and document.sections[0].header.paragraphs[0].text == "OCX"
    with zipfile.ZipFile(tmp_path / "letter.docx") as archive:
        assert b"template.main+xml" not in archive.read("[Content_Types].xml")

    sheet = api.merge(write_excel_template(tmp_path / "brand.xltx"), tmp_path / "sheet.xlsx", {"title": "Q3", "amount": 1500})
    assert _data(sheet)["missing"] == []
    cells = load_workbook(tmp_path / "sheet.xlsx")["Summary"]
    assert cells["A1"].value == "Q3" and cells["A1"].font.b is True and cells["A1"].font.color.rgb == "FFC00000"
    assert cells["B2"].value == 1500 and cells["B2"].number_format == "#,##0.00"

    deck_template = tmp_path / "brand.pptx"
    presentation = Presentation()
    box = presentation.slides.add_slide(presentation.slide_layouts[5]).shapes.title
    box.text_frame.text = "{{headline}}"
    box.text_frame.paragraphs[0].runs[0].font.size = Pt(40)
    presentation.save(deck_template)
    deck = api.merge(deck_template, tmp_path / "deck.pptx", {"headline": "Launch"})
    assert _data(deck)["replaced"] == 1
    title = Presentation(str(tmp_path / "deck.pptx")).slides[0].shapes.title.text_frame.paragraphs[0].runs[0]
    assert title.text == "Launch" and title.font.size == Pt(40)


def test_an_unfilled_placeholder_is_reported_not_blanked(tmp_path):
    result = _data(api.merge(write_word_template(tmp_path / "brand.dotx"), tmp_path / "out.docx", {"title": "T"}))
    assert "customer.name" in result["missing"]
    issues = _data(api.view(tmp_path / "out.docx", "issues"))["issues"]
    assert {item["code"] for item in issues} == {"unresolved_placeholder"}


def test_the_engine_is_self_contained():
    for module in sorted(ENGINE_DIR.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                assert not (node.module or "").startswith("app"), f"{module.name} imports {node.module}"
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("app") for alias in node.names), module.name


def test_no_officecli_reference_is_left_in_the_product():
    tracked = subprocess.run(
        ["git", "grep", "--untracked", "-l", "-i", "officecli", "--", "backend/app", "backend/pyproject.toml", "frontend/chat/src",
         "Dockerfile", "doc", "document"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert tracked.stdout.strip() == "", tracked.stdout
