"""Tests for Office template upload and corp identity profile generation."""

from pathlib import Path

import pytest

from tests.office_potx_support import office_potx_path
from tests.office_template_support import isolate_corp_identity_root


@pytest.fixture(autouse=True)
def _isolated_corp_identity_store(monkeypatch, tmp_path):
    isolate_corp_identity_root(monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_panel_upload_office_template_generates_ai_ready_pptx_template(client, auth_headers):
    template_path = office_potx_path("Templates-test-ai.potx")
    response = await client.post(
        "/admin/chat/api/panel/office-templates/upload",
        headers=auth_headers,
        files={
            "file": (
                template_path.name,
                template_path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.presentationml.template",
            )
        },
    )
    assert response.status_code == 200
    payload = response.json()
    template = payload["template"]
    assert template["doc_type"] == "pptx"
    assert template["path"].endswith(".potx")
    assert "AI-ready PPTX template generated" in template["description"]
    assert Path(template["path"]).exists()
    assert Path(template["source_path"]).exists()
    assert Path(template["package_manifest_path"]).exists()
    storage_contract = template["storage_contract"]
    assert storage_contract["storage_kind"] == "uploaded_source_with_generated_ai_template"
    assert storage_contract["source_path"] == template["source_path"]
    assert storage_contract["active_template_path"] == template["path"]
    assert storage_contract["ai_template_path"] == template["ai_template_path"]
    assert storage_contract["package_manifest_path"] == template["package_manifest_path"]
    assert storage_contract["has_import_package"] is True
    assert storage_contract["has_generated_ai_artifact"] is True
    assert Path(storage_contract["package_root"]).name
    assert Path(storage_contract["generated_artifact_root"]).parent == Path(storage_contract["package_root"])


@pytest.mark.asyncio
async def test_panel_upload_corp_identity_extracts_profile_and_sets_default(client, auth_headers):
    template_path = office_potx_path()
    response = await client.post(
        "/admin/chat/api/panel/corp-identities/upload",
        headers=auth_headers,
        files={
            "file": (
                template_path.name,
                template_path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.presentationml.template",
            )
        },
    )
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["name"]
    assert profile["summary"]["layout_count"] > 0
    assert profile["summary"]["corporate_safe_layout_count"] > 0
    assert profile["summary"]["icon_count"] > 0
    assert "Corporate Identity Guide" in profile["guide_markdown"]
    assert Path(profile["profile_root"]).exists()

    list_resp = await client.get("/admin/chat/api/panel/corp-identities", headers=auth_headers)
    assert list_resp.status_code == 200
    list_payload = list_resp.json()
    assert list_payload["default_profile_id"] == profile["id"]
    assert any(item["id"] == profile["id"] for item in list_payload["profiles"])

    detail_resp = await client.get(
        f"/admin/chat/api/panel/corp-identities/{profile['id']}",
        headers=auth_headers,
    )
    assert detail_resp.status_code == 200
    detail_payload = detail_resp.json()
    assert detail_payload["summary"]["theme_name"]
    assert detail_payload["layout_catalog"]["summary"]["total_layouts"] >= detail_payload["summary"]["layout_count"]
