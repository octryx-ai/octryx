"""Project repo quality config and runtime policy updates, and the project panel's optional sections."""

import uuid

import pytest

from app.models import Project


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_project_repo_quality_config_can_be_updated_via_admin_api(admin_client, db):
    project = Project(id=str(uuid.uuid4()), name="quality-project", config={}, is_active=True)
    db.add(project)
    await db.commit()

    list_resp = await admin_client.get("/admin/chat/api/panel/projects")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    listed = next(item for item in payload if item["id"] == project.id)
    assert listed["repo_code_quality"] == {}

    update_resp = await admin_client.put(
        f"/admin/chat/api/panel/projects/{project.id}/repo-quality",
        json={
            "repo_code_quality": {
                "default": {"test_runner": "pytest -q", "sast_runners": ["bandit"]},
                "repos": {"quality-project": {"coverage_threshold": 90}},
            }
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["repo_code_quality"]["default"]["test_runner"] == "pytest -q"
    assert update_resp.json()["repo_code_quality"]["repos"]["quality-project"]["coverage_threshold"] == 90


@pytest.mark.asyncio
async def test_project_panel_survives_optional_overview_section_failure(admin_client, db, monkeypatch):
    project = Project(id=str(uuid.uuid4()), name="partial-overview-project", config={}, is_active=True)
    db.add(project)
    await db.commit()

    async def broken_code_repositories(*args, **kwargs):
        raise RuntimeError("repository metadata unavailable")

    monkeypatch.setattr(
        "app.services.admin.project.admin_project_quality_overview.list_code_repositories",
        broken_code_repositories,
    )

    list_resp = await admin_client.get("/admin/chat/api/panel/projects")
    assert list_resp.status_code == 200, list_resp.text
    listed = next(item for item in list_resp.json() if item["id"] == project.id)
    assert listed["overview_status"] == "partial"
    assert listed["code_repositories"] == []
    assert any(error["section"] == "code_repositories" for error in listed["overview_errors"])


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_project_runtime_policy_can_be_updated_via_admin_api(admin_client, db):
    project = Project(id=str(uuid.uuid4()), name="runtime-policy-panel-project", config={}, is_active=True)
    db.add(project)
    await db.commit()

    update_resp = await admin_client.put(
        f"/admin/chat/api/panel/projects/{project.id}/runtime-policy",
        json={
            "runtime_policy": {
                "active_environment": "production",
                "default_bundle": {
                    "security_analyzer_chain": ["exec_policy", "llm_risk"],
                    "security_review_model": "security-model-v1",
                },
                "environment_bundles": {
                    "production": {
                        "execution_runtime_provider": "docker",
                        "llm_security_analyzer_review_threshold": 50,
                        "llm_security_analyzer_deny_threshold": 90,
                    }
                },
            }
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["runtime_policy"]["active_environment"] == "production"
    assert updated["effective_runtime_policy"]["execution_runtime_provider"] == "docker"
    assert updated["effective_runtime_policy"]["security_review_model"] == "security-model-v1"
    assert updated["effective_runtime_policy"]["llm_security_analyzer_review_threshold"] == 50

    list_resp = await admin_client.get("/admin/chat/api/panel/projects")
    assert list_resp.status_code == 200
    item = next(entry for entry in list_resp.json() if entry["id"] == project.id)
    assert item["runtime_policy"]["active_environment"] == "production"
    assert item["effective_runtime_policy"]["execution_runtime_provider"] == "docker"
