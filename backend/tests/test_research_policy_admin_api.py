from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project
from app.services.research_policy.defaults import default_research_policy_profiles
from tests.conftest import ADMIN_PASSWORD


async def _login_admin(client) -> None:
    resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert resp.status_code == 303


def _standard_policy_spec() -> dict:
    for profile in default_research_policy_profiles():
        if profile["key"] == "standard-research-document":
            return profile["spec"]
    raise AssertionError("standard research policy profile is missing")


async def _create_project(db) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        name=f"research-policy-api-{uuid.uuid4().hex[:8]}",
        config={},
        is_active=True,
    )
    db.add(project)
    await db.commit()
    return project


@pytest.mark.asyncio
async def test_research_policy_admin_api_lists_seeded_profiles(client):
    await _login_admin(client)

    resp = await client.get("/admin/chat/api/panel/research-policies")

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    profiles = {item["key"]: item for item in payload["profiles"]}
    assert payload["defaults"]["default_profile_key"] == "deep-research-document"
    assert payload["diagnostics"]["status"] == "valid"
    assert "standard-research-document" in profiles
    assert "deep-research-document" in profiles
    assert "scientific-literature-review" in profiles
    deep_version = profiles["deep-research-document"]["versions"][0]
    assert deep_version["status"] == "published"
    assert deep_version["diagnostics"]["status"] == "valid"
    assert deep_version["spec"]["evidence_archive"]["workspace_folder"] == "research"
    assert deep_version["spec"]["research_strategy"]["max_source_count"] == 120
    literature_version = profiles["scientific-literature-review"]["versions"][0]
    assert literature_version["diagnostics"]["status"] == "valid"
    assert literature_version["spec"]["source_policy"]["literature_policy"]["require_published_sources"] is True


@pytest.mark.asyncio
async def test_research_policy_admin_api_creates_profile_and_assigns_workspace(client, db):
    await _login_admin(client)
    project = await _create_project(db)
    spec = _standard_policy_spec()
    spec["research_strategy"]["target_source_count"] = 12
    spec["research_strategy"]["max_source_count"] = 30
    spec["output_policy"]["target_pages"]["target"] = 10
    spec["output_policy"]["target_pages"]["max"] = 14

    create_resp = await client.post(
        "/admin/chat/api/panel/research-policies",
        json={
            "key": f"custom-research-{uuid.uuid4().hex[:8]}",
            "name": "Custom Research Policy",
            "description": "Workspace-specific research policy.",
            "initial_spec": spec,
            "initial_version_status": "published",
            "notes": "Initial published test policy.",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    profile = create_resp.json()
    version = profile["versions"][0]
    assert version["version"] == 1
    assert version["status"] == "published"
    assert version["diagnostics"]["status"] == "valid"

    preview_before = await client.get(f"/admin/chat/api/panel/projects/{project.id}/research-policy")
    assert preview_before.status_code == 200, preview_before.text
    assert preview_before.json()["effective_policy"]["profile_key"] == "deep-research-document"

    assign_resp = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/research-policy",
        json={"profile_version_id": version["id"]},
    )
    assert assign_resp.status_code == 200, assign_resp.text
    assigned = assign_resp.json()
    assert assigned["assignment"]["profile_version_id"] == version["id"]
    assert assigned["effective_policy"]["source"] == "workspace_assignment"
    assert assigned["effective_policy"]["profile_key"] == profile["key"]
    assert assigned["effective_policy"]["spec"]["research_strategy"]["target_source_count"] == 12

    clear_resp = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/research-policy",
        json={"clear_assignment": True},
    )
    assert clear_resp.status_code == 200, clear_resp.text
    cleared = clear_resp.json()
    assert cleared["assignment"]["assignment_status"] == "inactive"
    assert cleared["effective_policy"]["profile_key"] == "deep-research-document"


@pytest.mark.asyncio
async def test_research_policy_admin_api_rejects_specs_without_research_evidence_archive(client):
    await _login_admin(client)
    spec = _standard_policy_spec()
    spec["evidence_archive"]["workspace_folder"] = "scratch"
    spec["evidence_archive"]["preserve_raw_sources"] = False

    resp = await client.post(
        "/admin/chat/api/panel/research-policies",
        json={
            "key": f"invalid-research-{uuid.uuid4().hex[:8]}",
            "name": "Invalid Research Policy",
            "initial_spec": spec,
            "initial_version_status": "published",
        },
    )

    assert resp.status_code == 400
    diagnostics = resp.json()["detail"]["diagnostics"]
    fields = {item["field"] for item in diagnostics["errors"]}
    assert "evidence_archive.workspace_folder" in fields
    assert "evidence_archive.preserve_raw_sources" in fields


@pytest.mark.asyncio
async def test_research_policy_admin_api_rejects_contradictory_literature_policy(client):
    await _login_admin(client)
    spec = _standard_policy_spec()
    spec["source_policy"]["research_mode"] = "literature"
    spec["source_policy"]["literature_policy"] = {
        "enabled": True,
        "mode": "literature",
        "require_published_sources": True,
        "exclude_preprints": False,
        "restrict_to_preferred_domains": True,
        "preferred_domains": ["semanticscholar.org"],
    }

    resp = await client.post(
        "/admin/chat/api/panel/research-policies",
        json={
            "key": f"invalid-literature-{uuid.uuid4().hex[:8]}",
            "name": "Invalid Literature Policy",
            "initial_spec": spec,
            "initial_version_status": "published",
        },
    )

    assert resp.status_code == 400
    diagnostics = resp.json()["detail"]["diagnostics"]
    fields = {item["field"] for item in diagnostics["errors"]}
    assert "source_policy.literature_policy.exclude_preprints" in fields


@pytest.mark.asyncio
async def test_research_policy_admin_api_blocks_assignment_of_draft_versions(client, db):
    await _login_admin(client)
    project = await _create_project(db)
    spec = _standard_policy_spec()

    create_resp = await client.post(
        "/admin/chat/api/panel/research-policies",
        json={
            "key": f"draft-research-{uuid.uuid4().hex[:8]}",
            "name": "Draft Research Policy",
            "initial_spec": spec,
            "initial_version_status": "draft",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    version_id = create_resp.json()["versions"][0]["id"]

    assign_resp = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/research-policy",
        json={"profile_version_id": version_id},
    )

    assert assign_resp.status_code == 400
    assert "published" in assign_resp.text

    published_resp = await client.put(
        f"/admin/chat/api/panel/research-policies/{create_resp.json()['id']}/versions/{version_id}",
        json={"status": "published"},
    )
    assert published_resp.status_code == 200, published_resp.text
    stored_project = (await db.execute(select(Project).where(Project.id == project.id))).scalar_one()
    assert stored_project.id == project.id
