"""Office template library and actions: the library round-trips runtime settings, keeps uploaded storage fields and the built-in default, and template paths and actions resolve per file type."""

import json

import pytest

from app.models import SystemConfig
from app.services.office.documents import (
    get_office_template_library,
    list_office_actions_for_path,
    resolve_office_action_for_path,
    resolve_office_template_path,
)
from tests.support.office_documents_service_support import _isolated_corp_identity_store  # noqa: F401
from tests.support.office_potx_support import office_potx_path


@pytest.mark.asyncio
async def test_office_template_library_round_trips_from_runtime_settings(db, tmp_path):
    template = tmp_path / "deck.potx"
    template.write_text("stub", encoding="utf-8")
    db.add(
        SystemConfig(
            key="agent.office_template_library",
            value=f'[{{"key":"deck","name":"Deck","doc_type":"pptx","path":"{template}","description":"Presentation","is_default":true}}]',
        )
    )
    await db.commit()

    library = await get_office_template_library(db=db, project_config=None)

    assert any(item["key"] == "deck" for item in library)
    assert any(item["doc_type"] == "pptx" for item in library)
    assert any(item["is_default"] is True for item in library if item["doc_type"] == "pptx")


@pytest.mark.asyncio
async def test_office_template_library_preserves_uploaded_storage_contract_fields(db, tmp_path):
    template = tmp_path / "deck-ai.potx"
    source = tmp_path / "source-deck.potx"
    manifest = tmp_path / "manifest.json"
    template.write_text("stub", encoding="utf-8")
    source.write_text("stub", encoding="utf-8")
    manifest.write_text("{}", encoding="utf-8")
    db.add(
        SystemConfig(
            key="agent.office_template_library",
            value=json.dumps(
                [
                    {
                        "key": "deck",
                        "name": "Deck",
                        "doc_type": "pptx",
                        "path": str(template),
                        "description": "Presentation",
                        "is_default": True,
                        "source_path": str(source),
                        "ai_template_path": str(template),
                        "package_manifest_path": str(manifest),
                        "storage_contract": {
                            "doc_type": "pptx",
                            "storage_kind": "uploaded_source_with_generated_ai_template",
                            "source_path": str(source),
                            "active_template_path": str(template),
                            "package_manifest_path": str(manifest),
                            "has_import_package": True,
                            "has_generated_ai_artifact": True,
                        },
                    }
                ]
            ),
        )
    )
    await db.commit()

    library = await get_office_template_library(db=db, project_config=None)

    deck = next(item for item in library if item["key"] == "deck")
    assert deck["source_path"] == str(source)
    assert deck["ai_template_path"] == str(template)
    assert deck["package_manifest_path"] == str(manifest)
    assert deck["storage_contract"]["storage_kind"] == "uploaded_source_with_generated_ai_template"
    assert deck["storage_contract"]["active_template_path"] == str(template)
    assert deck["storage_contract"]["has_import_package"] is True


@pytest.mark.asyncio
async def test_office_template_library_includes_builtin_ai_default_when_missing(db, tmp_path, monkeypatch):
    import app.services.office.template as template_service

    builtin_root = tmp_path / "template"
    builtin_dir = builtin_root / "templates-test-ai"
    builtin_dir.mkdir(parents=True)
    (builtin_dir / "Templates-test-ai.potx").write_bytes(office_potx_path("Templates-test-ai.potx").read_bytes())
    monkeypatch.setattr(template_service, "OFFICE_TEMPLATE_BUILTIN_ROOT", builtin_root)

    library = await get_office_template_library(db=db, project_config=None)

    assert any(item["key"] == "templates-test-ai-pptx" for item in library)
    assert any(item["is_default"] is True for item in library if item["doc_type"] == "pptx")


@pytest.mark.asyncio
async def test_resolve_office_template_path_prefers_template_key(db, tmp_path):
    template = tmp_path / "deck.potx"
    template.write_text("stub", encoding="utf-8")
    db.add(
        SystemConfig(
            key="agent.office_template_library",
            value=f'[{{"key":"deck","name":"Deck","doc_type":"pptx","path":"{template}","description":"","is_default":true}}]',
        )
    )
    await db.commit()

    resolved, entry = await resolve_office_template_path(
        db=db,
        project_config=None,
        workspace_root=tmp_path,
        template_key="deck",
        doc_type="pptx",
    )

    assert resolved == template.resolve()
    assert entry is not None
    assert entry["key"] == "deck"


def test_list_office_actions_for_path_is_file_type_specific():
    xlsx_actions = list_office_actions_for_path("/tmp/sample.xlsx")
    docx_actions = list_office_actions_for_path("/tmp/sample.docx")

    assert xlsx_actions["file_type"] == "xlsx"
    assert "forms" not in [item["id"] for item in xlsx_actions["actions"]]
    assert "formulas" in [item["id"] for item in xlsx_actions["actions"]]
    assert docx_actions["file_type"] == "docx"
    assert "forms" in [item["id"] for item in docx_actions["actions"]]


def test_resolve_office_action_for_path_returns_prompt_or_tool_plan():
    prompt_payload = resolve_office_action_for_path("/tmp/sample.pptx", action_id="slides", mode="prompt")
    plan_payload = resolve_office_action_for_path("/tmp/sample.pptx", action_id="slides", mode="tool_plan")

    assert prompt_payload["mode"] == "prompt"
    assert "summarize it slide by slide" in prompt_payload["text"].lower()
    assert plan_payload["mode"] == "tool_plan"
    assert "preferred views" in plan_payload["text"].lower()
