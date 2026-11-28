"""Corporate identity templates: creating and filling pptx, docx and xlsx documents uses the default corp identity template, companion templates are found and legacy profiles migrate."""

from pathlib import Path

import pytest

from app.models import SystemConfig
from app.services.corp_identity_service import (
    resolve_corp_identity_office_template_path,
    resolve_corp_identity_template_path,
    save_uploaded_corp_identity_profile,
)
from app.tools.context import ToolContext
from app.tools.office_impl._office_basic import CreateOfficeDocumentTool, FillOfficeTemplateTool
from tests.support.office_documents_service_support import _isolated_corp_identity_store  # noqa: F401
from tests.support.office_potx_support import office_potx_path
from tests.support.office_template_support import write_excel_template, write_word_template


@pytest.mark.asyncio
async def test_create_office_document_uses_default_corp_identity_template_for_pptx(db, tmp_path, monkeypatch):
    template_path = office_potx_path()
    profile = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )


    context = ToolContext(
        user_id="admin",
        project_ids=[],
        roles=["admin"],
        session_id="session-1",
        project_config={},
        db=db,
        workspace_root=str(tmp_path),
    )

    result = await CreateOfficeDocumentTool().execute(
        {
            "file_path": "deck.pptx",
            "doc_type": "pptx",
            "template_data": {"title": "Customer Pitch"},
        },
        context,
    )

    assert result["success"] is True
    assert result["template_path"] == profile["ai_template_path"]
    assert result["template_key"].startswith("corp-identity:")
    assert result["relative_path"] == "deck.pptx"
    assert (tmp_path / "deck.pptx").exists()


@pytest.mark.asyncio
async def test_fill_office_template_uses_default_corp_identity_template_for_pptx(db, tmp_path, monkeypatch):
    template_path = office_potx_path()
    profile = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )


    context = ToolContext(
        user_id="admin",
        project_ids=[],
        roles=["admin"],
        session_id="session-2",
        project_config={},
        db=db,
        workspace_root=str(tmp_path),
    )

    result = await FillOfficeTemplateTool().execute(
        {
            "output_path": "brand-deck.pptx",
            "data": {"title": "Launch", "agenda": ["Intro", "Roadmap"]},
        },
        context,
    )

    assert result["success"] is True
    assert result["template_path"] == profile["ai_template_path"]
    assert result["template_key"].startswith("corp-identity:")
    assert (tmp_path / "brand-deck.pptx").exists()


@pytest.mark.asyncio
async def test_resolve_corp_identity_office_template_path_finds_companion_word_and_excel_templates(db):
    template_path = office_potx_path()
    profile = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )
    ai_root = Path(profile["ai_template_path"]).parent
    word_template = ai_root / "brand-playbook.dotx"
    excel_template = ai_root / "brand-finance.xltx"
    write_word_template(word_template)
    write_excel_template(excel_template)

    resolved_word, word_detail = await resolve_corp_identity_office_template_path(db, doc_type="docx")
    resolved_excel, excel_detail = await resolve_corp_identity_office_template_path(db, doc_type="xlsx")

    assert resolved_word == word_template.resolve()
    assert resolved_excel == excel_template.resolve()
    assert word_detail["id"] == profile["id"]
    assert excel_detail["id"] == profile["id"]


@pytest.mark.asyncio
async def test_create_office_document_uses_default_corp_identity_template_for_docx_and_xlsx(db, tmp_path, monkeypatch):
    template_path = office_potx_path()
    profile = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )
    ai_root = Path(profile["ai_template_path"]).parent
    word_template = ai_root / "corp-identity.dotx"
    excel_template = ai_root / "corp-identity.xltx"
    write_word_template(word_template)
    write_excel_template(excel_template)


    context = ToolContext(
        user_id="admin",
        project_ids=[],
        roles=["admin"],
        session_id="session-docs",
        project_config={},
        db=db,
        workspace_root=str(tmp_path),
    )

    word_result = await CreateOfficeDocumentTool().execute(
        {
            "file_path": "brand-playbook.docx",
            "doc_type": "docx",
            "template_data": {"company": "Octryx"},
        },
        context,
    )
    excel_result = await CreateOfficeDocumentTool().execute(
        {
            "file_path": "brand-finance.xlsx",
            "doc_type": "xlsx",
            "template_data": {"company": "Octryx"},
        },
        context,
    )

    assert word_result["success"] is True
    assert word_result["template_path"] == str(word_template.resolve())
    assert word_result["template_key"].startswith("corp-identity:")
    assert excel_result["success"] is True
    assert excel_result["template_path"] == str(excel_template.resolve())
    assert excel_result["template_key"].startswith("corp-identity:")
    assert (tmp_path / "brand-playbook.docx").exists()
    assert (tmp_path / "brand-finance.xlsx").exists()


@pytest.mark.asyncio
async def test_fill_office_template_uses_default_corp_identity_template_for_docx_and_xlsx(db, tmp_path, monkeypatch):
    template_path = office_potx_path()
    profile = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )
    ai_root = Path(profile["ai_template_path"]).parent
    word_template = ai_root / "brand-playbook.dotx"
    excel_template = ai_root / "brand-finance.xltx"
    write_word_template(word_template)
    write_excel_template(excel_template)


    context = ToolContext(
        user_id="admin",
        project_ids=[],
        roles=["admin"],
        session_id="session-fill",
        project_config={},
        db=db,
        workspace_root=str(tmp_path),
    )

    word_result = await FillOfficeTemplateTool().execute(
        {
            "output_path": "proposal.docx",
            "data": {"company": "Octryx"},
        },
        context,
    )
    excel_result = await FillOfficeTemplateTool().execute(
        {
            "output_path": "budget.xlsx",
            "data": {"company": "Octryx"},
        },
        context,
    )

    assert word_result["success"] is True
    assert word_result["template_path"] == str(word_template.resolve())
    assert word_result["template_key"].startswith("corp-identity:")
    assert excel_result["success"] is True
    assert excel_result["template_path"] == str(excel_template.resolve())
    assert excel_result["template_key"].startswith("corp-identity:")
    assert (tmp_path / "proposal.docx").exists()
    assert (tmp_path / "budget.xlsx").exists()


@pytest.mark.asyncio
async def test_resolve_corp_identity_template_path_migrates_legacy_profile_without_ai_template(db):
    template_path = office_potx_path()
    profile = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )

    from sqlalchemy import select

    registry_config = (
        await db.execute(select(SystemConfig).where(SystemConfig.key == "agent.corp_identity_registry"))
    ).scalar_one()
    import json

    registry = json.loads(registry_config.value)
    registry[0].pop("ai_template_path", None)
    registry[0].pop("package_manifest_path", None)
    registry[0].pop("asset_catalog_path", None)
    registry[0].pop("layout_inventory_path", None)
    registry[0].pop("role_matrix_path", None)
    registry_config.value = json.dumps(registry)
    await db.commit()

    resolved_path, detail = await resolve_corp_identity_template_path(db)

    assert resolved_path.exists()
    assert resolved_path.name.endswith("-ai.potx")
    assert str(detail["id"]) == profile["id"]
