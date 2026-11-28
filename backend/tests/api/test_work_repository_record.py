"""Contract: the repository record is the one repository home."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.workspaces.workspace_repositories import router
from app.db import get_db
from app.models import CodeRepository, Project, User, UserProject, WorkRepositoryProfile
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.auth import get_current_user
from app.services.secure_work.config_visibility import MASK


@pytest.fixture
async def api(db):
    app = FastAPI()
    app.include_router(router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://repos.test") as client:
        yield client, state


async def _world(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project, other = Project(name=f"r-{uuid.uuid4().hex[:6]}", config={}), Project(name=f"r-{uuid.uuid4().hex[:6]}", config={})
    db.add_all([project, other])
    await db.flush()
    source = KnowledgeSourceConnector(project_id=project.id, connector_key="claims-api", kind="git_repository", scope={})
    db.add(source)
    await db.flush()
    repo = CodeRepository(project_id=project.id, name="claims-api", repo_root="/central/claims-api", provider="knowledge_snapshot",
                          default_branch="main", config_json={"central_source": {"connector_id": source.id}})
    foreign = CodeRepository(project_id=other.id, name="secret", repo_root="/central/secret", provider="local", config_json={})
    member = User(username=f"m-{uuid.uuid4().hex[:6]}", email=f"m-{uuid.uuid4().hex[:6]}@example.test", password_hash="x",
                  display_name="m", account_type="human", is_active=True)
    db.add_all([repo, foreign, member])
    await db.flush()
    db.add(UserProject(user_id=member.id, project_id=project.id, role="member"))
    await db.commit()
    return admin, member, project.id, repo


async def test_records_list_and_the_coding_setup_is_saved_on_the_record(db, api):
    client, state = api
    admin, member, project_id, repo = await _world(db)
    base = f"/api/v1/workspaces/{project_id}/repositories"
    state["user"] = admin
    listed = (await client.get(base)).json()["items"]
    assert [entry["name"] for entry in listed] == ["claims-api"]
    assert listed[0]["source"] == {"kind": "knowledge_source", "name": "claims-api"}
    assert listed[0]["coding_setup"] == {"configured": [], "missing": ["build", "test", "lint"]}
    saved = await client.put(f"{base}/{repo.id}/coding-setup", json={
        "owners": ["Claims backend team"], "build_commands": ["./gradlew build"], "test_commands": ["./gradlew test"],
        "secret_references": ["vault://claims/read"], "jira_project_keys": ["CLM"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["summary"] == {"configured": ["build", "test"], "missing": ["lint"]}
    await db.refresh(repo)
    assert repo.config_json["coding_setup"]["owners"] == ["Claims backend team"]
    assert "jira_project_keys" not in repo.config_json["coding_setup"], "D3"
    projection = (await db.execute(select(WorkRepositoryProfile).where(WorkRepositoryProfile.code_repository_id == repo.id))).scalar_one()
    assert (projection.test_commands_json, projection.default_branch, projection.profile_source) == (["./gradlew test"], "main", "code_repository")

    state["user"] = member
    read = (await client.get(f"{base}/{repo.id}/coding-setup")).json()["coding_setup"]
    assert read["secret_references"] == [MASK]
    assert (await client.put(f"{base}/{repo.id}/coding-setup", json={"owners": []})).status_code == 403
    state["user"] = admin
    kept = await client.put(f"{base}/{repo.id}/coding-setup", json={"secret_references": [MASK, "vault://claims/new"]})
    assert kept.status_code == 200
    await db.refresh(repo)
    assert repo.config_json["coding_setup"]["secret_references"] == ["vault://claims/read", "vault://claims/new"]
    other = (await db.execute(select(CodeRepository).where(CodeRepository.name == "secret"))).scalar_one()
    assert (await client.get(f"{base}/{other.id}/coding-setup")).status_code == 404


async def test_the_environment_file_is_a_validated_pointer_on_the_record(db, api):
    client, state = api
    admin, _member, project_id, repo = await _world(db)
    base = f"/api/v1/workspaces/{project_id}/repositories/{repo.id}/coding-setup"
    state["user"] = admin
    refused = await client.put(base, json={"environment_file": "../other/.octryx/environment.json"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "invalid_environment_file"
    saved = await client.put(base, json={"environment_file": "coffee/web/claude/.octryx/environment.json"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["coding_setup"]["environment_file"] == "coffee/web/claude/.octryx/environment.json"
    kept = await client.put(base, json={"owners": ["Coffee"]})
    assert kept.json()["coding_setup"]["environment_file"] == "coffee/web/claude/.octryx/environment.json"
    cleared = await client.put(base, json={"environment_file": None})
    assert cleared.json()["coding_setup"]["environment_file"] is None
    await db.refresh(repo)
    assert "environment_file" not in repo.config_json["coding_setup"]
