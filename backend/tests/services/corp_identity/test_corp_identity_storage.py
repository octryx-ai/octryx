import json
from pathlib import Path

import pytest

from app.services.corp_identity_service import (
    get_corp_identity_profile_detail,
    list_corp_identity_profiles,
    reextract_corp_identity_profile,
    save_uploaded_corp_identity_profile,
)
from app.services.system_config import get_system_config_value, set_system_config_value
from tests.support.office_potx_support import office_potx_path
from tests.support.office_template_support import isolate_corp_identity_root, office_docx_template_bytes


@pytest.fixture(autouse=True)
def _isolated_corp_identity_store(monkeypatch, tmp_path):
    isolate_corp_identity_root(monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_corp_identity_detail_describes_rebuildable_storage(db):
    template_path = office_potx_path()
    profile = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )

    detail = await get_corp_identity_profile_detail(db, profile["id"])
    lifecycle = detail["storage_lifecycle"]

    assert lifecycle["reextract_supported"] is True
    assert any(
        entry["kind"] == "source_upload" and entry["path"].endswith(template_path.name)
        for entry in lifecycle["source_of_truth"]
    )
    assert any(
        entry["kind"] == "extracted_cache" and entry["path"].endswith("/_extracted")
        for entry in lifecycle["rebuildable"]
    )
    assert any(path.endswith("brand-profile.json") for path in lifecycle["safe_cleanup_paths"])
    assert any(path.endswith("layout-catalog.json") for path in lifecycle["safe_cleanup_paths"])
    assert any(path.endswith("icon-catalog.json") for path in lifecycle["safe_cleanup_paths"])
    assert any(path.endswith("llm-guide.md") for path in lifecycle["safe_cleanup_paths"])
    assert any(path.endswith(f"{template_path.stem}-ai.potx") for path in lifecycle["safe_cleanup_paths"])
    assert any(path.endswith(f"{template_path.stem}-ai.pptx") for path in lifecycle["safe_cleanup_paths"])
    assert any(path.endswith("example-slide-map.json") for path in lifecycle["safe_cleanup_paths"])


@pytest.mark.asyncio
async def test_corp_identity_detail_keeps_companion_templates_out_of_safe_cleanup(db):
    template_path = office_potx_path()
    profile = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )

    ai_root = Path(profile["ai_template_path"]).parent
    companion_path = ai_root / "corp-brand.dotx"
    companion_path.write_bytes(b"word-template")

    detail = await get_corp_identity_profile_detail(db, profile["id"])
    lifecycle = detail["storage_lifecycle"]

    assert any(entry["path"] == str(companion_path.resolve()) for entry in lifecycle["retained_companions"])
    assert str(companion_path.resolve()) not in lifecycle["safe_cleanup_paths"]


@pytest.mark.asyncio
async def test_duplicate_presentation_upload_reuses_existing_profile(db):
    template_path = office_potx_path()

    first = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )
    second = await save_uploaded_corp_identity_profile(
        db,
        file_name=f"duplicate-{template_path.name}",
        file_bytes=template_path.read_bytes(),
    )
    payload = await list_corp_identity_profiles(db)

    assert second["id"] == first["id"]
    assert second["profile_root"] == first["profile_root"]
    assert len(payload["profiles"]) == 1
    assert payload["profiles"][0]["source_content_identity"] == first["source_content_identity"]


@pytest.mark.asyncio
async def test_duplicate_word_upload_reuses_existing_profile(db):
    file_bytes = office_docx_template_bytes()
    first = await save_uploaded_corp_identity_profile(
        db,
        file_name="corp-brand.dotx",
        file_bytes=file_bytes,
    )
    second = await save_uploaded_corp_identity_profile(
        db,
        file_name="copy-of-corp-brand.dotx",
        file_bytes=file_bytes,
    )
    payload = await list_corp_identity_profiles(db)

    assert second["id"] == first["id"]
    assert second["profile_root"] == first["profile_root"]
    assert second["summary"]["office_template_type"] == "docx"
    assert len(payload["profiles"]) == 1


@pytest.mark.asyncio
async def test_duplicate_upload_ignores_stale_profile_root(db):
    template_path = office_potx_path()
    first = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )
    raw_registry = await get_system_config_value(db, "agent.corp_identity_registry")
    registry = json.loads(raw_registry or "[]")
    stale_root = Path(registry[0]["profile_root"])
    registry[0]["profile_root"] = str((stale_root.parent / f"{stale_root.name}-missing").resolve())
    await set_system_config_value(
        db,
        key="agent.corp_identity_registry",
        value=json.dumps(registry),
        description="Corporate identity profiles and Office templates for duplicate upload tests.",
    )

    second = await save_uploaded_corp_identity_profile(
        db,
        file_name=f"stale-copy-{template_path.name}",
        file_bytes=template_path.read_bytes(),
    )
    payload = await list_corp_identity_profiles(db)

    assert second["id"] != first["id"]
    assert len(payload["profiles"]) == 1
    assert payload["profiles"][0]["id"] == second["id"]


@pytest.mark.asyncio
async def test_uploaded_presentation_profile_cleans_rebuildable_extracted_cache(db):
    template_path = office_potx_path()

    profile = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )
    extracted_dir = Path(profile["profile_root"]) / "_extracted"
    detail = await get_corp_identity_profile_detail(db, profile["id"])
    extracted_entry = next(
        entry for entry in detail["storage_lifecycle"]["rebuildable"] if entry["kind"] == "extracted_cache"
    )

    assert not extracted_dir.exists()
    assert extracted_entry["exists"] is False


@pytest.mark.asyncio
async def test_reextract_profile_cleans_rebuildable_extracted_cache_again(db):
    template_path = office_potx_path()

    profile = await save_uploaded_corp_identity_profile(
        db,
        file_name=template_path.name,
        file_bytes=template_path.read_bytes(),
    )
    refreshed = await reextract_corp_identity_profile(db, profile["id"])
    extracted_dir = Path(refreshed["profile_root"]) / "_extracted"
    detail = await get_corp_identity_profile_detail(db, refreshed["id"])
    extracted_entry = next(
        entry for entry in detail["storage_lifecycle"]["rebuildable"] if entry["kind"] == "extracted_cache"
    )

    assert not extracted_dir.exists()
    assert extracted_entry["exists"] is False
