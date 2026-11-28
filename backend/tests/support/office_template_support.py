"""Reusable Office document fixtures for tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

from tests.support.office_potx_support import _fixture_dir, _relationship_xml


def office_docx_template_bytes() -> bytes:
    path = _fixture_dir() / "corp-brand.dotx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
</Types>""",
        )
        zf.writestr(
            "_rels/.rels",
            _relationship_xml(
                [
                    (
                        "rId1",
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
                        "word/document.xml",
                    )
                ]
            ),
        )
        zf.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>Corporate Identity Guide</w:t></w:r></w:p></w:body>
</w:document>""",
        )
        zf.writestr(
            "word/theme/theme1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Test Brand">
  <a:themeElements>
    <a:clrScheme name="Test Brand"><a:accent1><a:srgbClr val="2A3F6B"/></a:accent1></a:clrScheme>
    <a:fontScheme name="Test Brand Fonts"><a:majorFont><a:latin typeface="Aptos"/></a:majorFont></a:fontScheme>
  </a:themeElements>
</a:theme>""",
        )
    return path.read_bytes()


def _as_template_package(path: Path, document_type: str, template_type: str) -> None:
    data = path.read_bytes()
    rebuilt = Path(str(path) + ".tmp")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "[Content_Types].xml":
                payload = payload.replace(document_type.encode(), template_type.encode())
            target.writestr(item, payload)
    rebuilt.replace(path)
    assert data != path.read_bytes()


def write_word_template(path: Path) -> Path:
    from docx import Document
    from docx.shared import Pt, RGBColor

    document = Document()
    document.sections[0].header.paragraphs[0].text = "{{company}}"
    document.add_heading("{{title}}", level=1)
    paragraph = document.add_paragraph()
    lead = paragraph.add_run("Prepared for {{cust")
    lead.bold = True
    lead.font.size = Pt(14)
    lead.font.color.rgb = RGBColor(0x2A, 0x3F, 0x6B)
    paragraph.add_run("omer.name}} on {{date}}")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Total"
    table.cell(0, 1).text = "{{total}}"
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    _as_template_package(
        path,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
    )
    return path


def write_excel_template(path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Summary"
    sheet["A1"] = "{{title}}"
    sheet["A1"].font = Font(b=True, color="FFC00000", sz=16)
    sheet["A2"] = "Amount"
    sheet["B2"] = "{{amount}}"
    sheet["B2"].number_format = "#,##0.00"
    workbook.template = True
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def isolate_corp_identity_root(monkeypatch, root: Path) -> Path:
    from app.services import corp_identity_service

    store = (root / "corp-identities").resolve()
    store.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(corp_identity_service, "CORP_IDENTITY_ROOT", store)
    return store
