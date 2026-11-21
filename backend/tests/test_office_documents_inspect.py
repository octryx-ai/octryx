"""Inspecting and previewing office documents: inspector shapes, Word-only forms, closed errors and escaped in-process preview HTML."""

from pathlib import Path

import pytest

from app.services.office import documents as office_documents
from app.services.office.documents import inspect_office_document, render_office_preview_html
from app.services.office.engine import api as office_engine
from tests.office_documents_service_support import _isolated_corp_identity_store  # noqa: F401


def _report_docx(path: Path) -> Path:
    office_engine.create(path)
    office_engine.add(path, "/body", "heading", {"text": "Intro", "level": 1})
    office_engine.add(path, "/body", "paragraph", {"text": "Hello {{name}}"})
    office_engine.add(path, "/body", "table", {"headers": ["A", "B"], "rows": [["1", "2"]]})
    return path


@pytest.mark.asyncio
async def test_inspect_office_document_modes_produce_the_inspector_shapes(tmp_path):
    document = _report_docx(tmp_path / "sample.docx")

    async def inspect(mode: str) -> dict:
        return await inspect_office_document(workspace_root=tmp_path, path=str(document), mode=mode)

    stats, text, issues, outline, annotated, forms = [
        await inspect(mode) for mode in ("stats", "text", "issues", "outline", "annotated", "forms")
    ]

    assert stats["stats"]["paragraphs"] >= 2 and stats["summary"]["style_count"] >= 2
    assert [item["type"] for item in text["content"]["elements"]] == ["heading", "paragraph", "table"]
    assert issues["summary"]["count"] == 1
    assert issues["content"]["issues"][0]["code"] == "unresolved_placeholder"
    assert outline["summary"]["headings"] == 1 and outline["summary"]["tables"] == 1
    assert "Hello {{name}}" in annotated["content"]["Content"]
    assert forms["summary"] == {"protection": "none", "protection_enforced": False, "field_count": 0}


@pytest.mark.asyncio
async def test_inspect_forms_is_word_only_and_unreadable_files_are_closed_errors(tmp_path):
    deck = tmp_path / "deck.pptx"
    office_engine.create(deck)
    broken = tmp_path / "broken.docx"
    broken.write_text("not a package", encoding="utf-8")

    with pytest.raises(office_documents.OfficeDocumentError) as forms_error:
        await inspect_office_document(workspace_root=tmp_path, path=str(deck), mode="forms")
    with pytest.raises(office_documents.OfficeDocumentError) as broken_error:
        await inspect_office_document(workspace_root=tmp_path, path=str(broken), mode="text")

    assert forms_error.value.code == "office_unsupported_element"
    assert broken_error.value.code == "office_document_unreadable"


@pytest.mark.asyncio
async def test_render_office_preview_html_is_in_process_and_escaped(tmp_path):
    document = _report_docx(tmp_path / "sample.docx")
    office_engine.add(document, "/body", "paragraph", {"text": "<script>alert(1)</script>"})

    html = await render_office_preview_html(workspace_root=tmp_path, path=str(document))

    assert html.startswith("<!doctype html>")
    assert "<h1>Intro</h1>" in html and "<table>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


@pytest.mark.asyncio
async def test_a_rendered_preview_without_libreoffice_is_an_explicit_page(tmp_path, monkeypatch):
    from app.services.office import render, render_sandbox
    from app.web._helpers.office_preview import office_preview_response

    document = _report_docx(tmp_path / "sample.docx")
    # No no-network wrapper and no sidecar: the renderer must refuse rather than render with a network.
    monkeypatch.delenv(render.SOCKET_ENV, raising=False)
    monkeypatch.setattr(render_sandbox, "isolation_prefix", lambda: None)

    unavailable = await office_preview_response(document, workspace_root=tmp_path, fmt="pdf")
    structural = await office_preview_response(document, workspace_root=tmp_path, fmt="html")

    assert unavailable.status_code == 503 and b"office_preview_unavailable" in unavailable.body
    assert structural.status_code == 200 and b"<h1>Intro</h1>" in structural.body
    assert (await render.render_check(document)) == {"status": "office_preview_unavailable"}
