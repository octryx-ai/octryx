from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation

from app.services.corp_identity_service import save_uploaded_corp_identity_profile
from app.tools.context import ToolContext
from app.tools.office_impl._office_excel_scripts import BuildExcelTemplateScriptTool
from app.tools.office_impl._office_presentation_script import BuildPresentationScriptTool
from app.tools.office_impl._office_word_scripts import BuildWordTemplateScriptTool
from tests.support.office_potx_support import office_potx_path
from tests.support.office_template_support import isolate_corp_identity_root, write_excel_template, write_word_template


@pytest.fixture(autouse=True)
def _isolated_corp_identity_store(monkeypatch, tmp_path):
    isolate_corp_identity_root(monkeypatch, tmp_path)


def test_build_presentation_script_generates_chart_and_process_flow_handlers():
    tool = BuildPresentationScriptTool()

    code = tool._generate_script(
        source_potx="/tmp/corp.potx",
        output_pptx="/tmp/deck.pptx",
        orig_slides=110,
        clone_order=[1, 3, 3],
        slides=[
            {"layout_type": "title", "title": "LLM Report", "subtitle": "Q4"},
            {
                "layout_type": "table",
                "title": "KPI Table",
                "headers": ["Metric", "Value"],
                "rows": [["Cycle Time", "-18%"], ["Quality", "+11%"]],
            },
            {
                "layout_type": "chart",
                "title": "Adoption Trend",
                "subtitle": "Usage by quarter",
                "chart": {
                    "chart_type": "line",
                    "categories": ["Q1", "Q2", "Q3"],
                    "series": [{"name": "Usage", "values": [12, 18, 27]}],
                },
            },
            {
                "layout_type": "process_flow",
                "title": "Governance Flow",
                "steps": [
                    {"title": "Prompt"},
                    {"title": "Review", "body": "Policy gate"},
                    {"title": "Release"},
                ],
            },
        ],
    )

    compile(code, "<build_presentation_script>", "exec")
    assert "officecli" not in code
    assert "from pptx import Presentation" in code
    assert "build.clone_slide(PRS" in code
    assert "def add_slide_chart" in code
    assert "def add_slide_table" in code
    assert "def render_process_flow" in code
    assert "add_slide_table(2," in code
    assert "add_slide_chart(3," in code
    assert "render_process_flow(4," in code
    assert "add_slide_connector" in code
    assert "build_visuals()" in code
    assert "tailEnd" in code


def test_build_word_template_script_generates_supported_layout_handlers():
    tool = BuildWordTemplateScriptTool()

    code = tool._generate_script(
        template_path="/tmp/brand.dotx",
        output_path="/tmp/brand-report.docx",
        template_data={"company": "Octryx"},
        citation_style="ieee",
        sources=[
            {
                "id": "src-1",
                "title": "LLM Adoption in Enterprises",
                "authors": ["Jane Smith"],
                "url": "https://example.com/llm-enterprise",
                "year": "2025",
            }
        ],
        include_bibliography=True,
        sections=[
            {"layout_type": "title_page", "title": "Executive Summary", "subtitle": "Q4"},
            {
                "layout_type": "toc",
                "title": "Inhalt",
            },
            {
                "layout_type": "table",
                "title": "KPIs",
                "headers": ["Metric", "Value"],
                "rows": [["Revenue", "42"]],
                "citations": ["src-1"],
            },
            {
                "layout_type": "chart",
                "title": "Usage Trend",
                "chart": {
                    "chart_type": "column",
                    "categories": ["Q1", "Q2"],
                    "series": [{"name": "Assistants", "values": [10, 18]}],
                },
                "citations": ["src-1"],
            },
            {
                "layout_type": "diagram",
                "title": "Process",
                "steps": [{"title": "Input"}, {"title": "Check"}, {"title": "Deploy"}],
                "citations": ["src-1"],
            },
            {"layout_type": "formula", "title": "Growth", "formula": r"y = \frac{{a}}{{b}}", "citations": ["src-1"]},
        ],
    )

    compile(code, "<build_word_template_script>", "exec")
    assert "officecli" not in code
    assert "from docx import Document" in code
    assert "fill_word(document, TEMPLATE_DATA)" in code
    assert "CITATION_STYLE = 'ieee'" in code
    assert 'layout == "table"' in code
    assert 'layout == "chart"' in code
    assert 'layout in {"diagram", "process_flow"}' in code
    assert 'layout == "formula"' in code
    assert "_format_inline_citation" in code
    assert "_render_bibliography" in code
    assert "render_table(section)" in code
    assert "add_equation(formula)" in code
    assert "def add_toc" in code
    assert 'layout == "toc"' in code
    assert "add_docx_chart(DOC, spec" in code
    assert "flow_png(steps" in code
    assert "doi" in code
    assert "isbn" in code


def test_build_excel_template_script_generates_sheet_and_chart_handlers():
    tool = BuildExcelTemplateScriptTool()

    code = tool._generate_script(
        template_path="/tmp/brand.xltx",
        output_path="/tmp/brand-report.xlsx",
        template_data={"company": "Octryx"},
        sheets=[
            {
                "name": "Summary",
                "layout_type": "kpi_summary",
                "kpis": [{"label": "Revenue", "value": 42, "numFmt": "$#,##0"}],
            },
            {
                "name": "Trend",
                "layout_type": "chart",
                "headers": ["Month", "Revenue"],
                "rows": [["Jan", 10], ["Feb", 12]],
                "chart": {"chart_type": "line", "title": "Revenue"},
                "sparklines": [{"cell": "C2", "range": "A2:B2", "type": "line"}],
                "conditional_formats": [{"sqref": "B2:B3", "type": "databar", "color": "63C384"}],
                "validations": [{"sqref": "A2:A3", "type": "list", "formula1": "Jan,Feb"}],
                "pivot_tables": [{"source": "Trend!A1:B3", "rows": ["Month"], "values": ["Revenue:sum"]}],
                "auto_filter_range": "A1:B3",
            },
        ],
    )

    compile(code, "<build_excel_template_script>", "exec")
    assert "officecli" not in code
    assert "from openpyxl import Workbook, load_workbook" in code
    assert 'layout == "kpi_summary"' in code
    assert 'layout == "matrix"' in code
    assert 'layout == "chart"' in code
    assert 'layout == "pivot_table"' in code
    assert "add_chart(sheet_name, chart)" in code
    assert "add_sparkline(sheet_name, sparkline)" in code
    assert "add_validation(sheet_name, validation_spec)" in code
    assert "add_conditional_format(sheet_name, cf_spec)" in code
    assert "add_pivot_table(sheet_name, pivot_spec)" in code
    assert "extras.write_sparklines(OUTPUT, SPARKLINES)" in code


def _context(db, tmp_path, session_id: str) -> ToolContext:
    return ToolContext(
        user_id="admin", project_ids=[], roles=["admin"], session_id=session_id, project_config={}, db=db,
        workspace_root=str(tmp_path),
    )


async def _corp_identity_root(db) -> Path:
    template_path = office_potx_path()
    profile = await save_uploaded_corp_identity_profile(
        db, file_name=template_path.name, file_bytes=template_path.read_bytes()
    )
    return Path(profile["ai_template_path"]).parent


@pytest.mark.asyncio
async def test_build_word_template_script_runs_on_the_corp_identity_dotx(db, tmp_path):
    word_template = write_word_template(await _corp_identity_root(db) / "corp-brand.dotx")

    result = await BuildWordTemplateScriptTool().execute(
        {
            "file_path": "proposal.docx",
            "template_data": {"title": "Proposal", "customer": {"name": "ACME"}, "date": "2026-10-09",
                              "total": "42", "company": "Octryx"},
            "citation_style": "ieee",
            "sources": [{"id": "src-1", "title": "Enterprise LLM Governance", "authors": ["Analyst Team"], "year": "2025"}],
            "sections": [
                {"layout_type": "title_page", "title": "Proposal", "subtitle": "Octryx"},
                {"layout_type": "bullets", "title": "Goals", "bullets": ["Standardize", "Reuse"], "citations": ["src-1"]},
                {"layout_type": "chart", "title": "Usage", "chart": {"chart_type": "column", "categories": ["Q1", "Q2"],
                                                                      "series": [{"name": "Users", "values": [10, 18]}]}},
                {"layout_type": "process_flow", "title": "Flow", "steps": [{"title": "Input"}, {"title": "Release"}]},
            ],
        },
        _context(db, tmp_path, "session-word-builder"),
    )

    assert result["success"] is True, result
    assert result["template_path"] == str(word_template.resolve())
    assert result["template_key"].startswith("corp-identity:")
    assert result["normalized_document_type"] is True
    assert result["validation"]["valid"] is True and result["validation"]["issue_count"] == 0
    assert result["stats"]["charts"] == 1 and result["stats"]["images"] == 1
    document = Document(str(tmp_path / "proposal.docx"))
    filled = next(p for p in document.paragraphs if p.text.startswith("Prepared for"))
    assert filled.text == "Prepared for ACME on 2026-10-09"
    assert filled.runs[0].bold is True and filled.runs[0].font.size.pt == 14
    assert "[1]" in "\n".join(p.text for p in document.paragraphs)
    assert (tmp_path / "proposal.docx.build.py").exists()


@pytest.mark.asyncio
async def test_build_excel_template_script_runs_on_the_corp_identity_xltx(db, tmp_path):
    write_excel_template(await _corp_identity_root(db) / "corp-brand.xltx")

    result = await BuildExcelTemplateScriptTool().execute(
        {
            "file_path": "kpi.xlsx",
            "template_data": {"title": "KPIs", "amount": 1234.5},
            "sheets": [
                {"name": "Summary", "layout_type": "kpi_summary", "kpis": [{"label": "Revenue", "value": 42}]},
                {"name": "Trend", "layout_type": "chart", "headers": ["Month", "Value"], "rows": [["Jan", 10], ["Feb", 12]],
                 "chart": {"chart_type": "line", "title": "Trend"}, "sparklines": [{"cell": "D3", "range": "B3:B4"}],
                 "pivot_tables": [{"source": "Trend!A1:B3", "rows": ["Month"], "values": ["Value"]}]},
            ],
        },
        _context(db, tmp_path, "session-excel-builder"),
    )

    assert result["success"] is True, result
    assert result["template_key"].startswith("corp-identity:")
    assert result["sheet_names"] == ["Summary", "Trend"]
    workbook = load_workbook(tmp_path / "kpi.xlsx")
    summary = workbook["Summary"]
    assert summary["B2"].value == 1234.5 and summary["B2"].number_format == "#,##0.00"
    assert summary["A1"].value == "KPIs" and summary["A1"].font.b is True
    assert summary["A1"].font.color.rgb == "FFC00000"
    assert len(workbook["Trend"]._charts) == 1
    assert "pivot on Trend" in result["stdout"]
    import zipfile

    with zipfile.ZipFile(tmp_path / "kpi.xlsx") as archive:
        assert b"sparklineGroup" in b"".join(archive.read(name) for name in archive.namelist() if "worksheets/" in name)


@pytest.mark.asyncio
async def test_build_presentation_script_clones_the_corp_identity_slides(db, tmp_path):
    await _corp_identity_root(db)

    result = await BuildPresentationScriptTool().execute(
        {
            "file_path": "deck.pptx",
            "slides": [
                {"layout_type": "title", "title": "Quarterly Review", "subtitle": "Q3"},
                {"layout_type": "chart", "title": "Trend",
                 "chart": {"chart_type": "line", "categories": ["Q1", "Q2"], "series": [{"name": "Revenue", "values": [1, 2]}]}},
                {"layout_type": "process_flow", "title": "Flow", "steps": [{"title": "Plan"}, {"title": "Ship"}]},
            ],
        },
        _context(db, tmp_path, "session-deck-builder"),
    )

    assert result["success"] is True, result
    assert result["slide_count"] == 3
    assert result["layout_check"]["source"] == "slide_gate"
    assert result["validation"]["valid"] is True
    deck = Presentation(str(tmp_path / "deck.pptx"))
    assert len(deck.slides) == 3
    assert any(shape.has_chart for shape in deck.slides[1].shapes)
    assert "Quarterly Review" in [shape.text_frame.text for shape in deck.slides[0].shapes if shape.has_text_frame]
