"""``Project.config`` is never a connection source.

The demo seed creates Workspace tool entries instead of ``Project.config`` URLs, the worker heartbeat
counts a connector as verified only through a Workspace entry it may use, and the admin config write
paths refuse connection keys.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import bootstrap
from app.bootstrap import seed_database
from app.models import AgentWorker, BuiltInToolConfig, DistributedWorkerRegistration, Project
from app.services.tool_config import upsert_tool_config
from app.services.tool_config.url_userinfo import carries_userinfo
from app.services.worker_pool.runtime import DistributedWorker


async def _project(db, config: dict) -> str:
    project = Project(name=f"conn-keys-{uuid.uuid4().hex[:8]}", config=config)
    db.add(project)
    await db.commit()
    return project.id


async def _entries(db, project_id: str) -> dict[str, tuple[bool, dict]]:
    rows = (await db.execute(select(BuiltInToolConfig).where(BuiltInToolConfig.project_id == project_id))).scalars()
    return {row.tool_name: (row.is_active, dict(row.config)) for row in rows}


async def _config(db, project_id: str) -> dict:
    project = await db.get(Project, project_id)
    await db.refresh(project)
    return dict(project.config)


@pytest.mark.asyncio
async def test_a_freshly_seeded_demo_workspace_uses_active_tool_entries(db, monkeypatch):
    legacy_demo = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    legacy_demo.name = "demo-legacy"
    await db.commit()
    monkeypatch.setattr(bootstrap.settings, "seed_demo_project", True)

    await seed_database(db)

    demo = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    assert demo.config == {"k8s_context": "demo-cluster"}
    assert await _entries(db, demo.id) == {
        tool: (True, {f"{tool}_url": url}) for tool, url in bootstrap.DEMO_TOOL_TARGETS.items()
    }


async def _verified(db, project_id: str) -> bool:
    """One heartbeat's ``connectors_verified`` for a fresh worker of ``project_id`` (its own sessions)."""
    worker = AgentWorker(id=str(uuid.uuid4()), project_id=project_id, name="Verify", role="Ops", is_active=True)
    db.add(worker)
    db.add(DistributedWorkerRegistration(worker_id=worker.id, project_id=project_id, backend="database",
                                         status="ready", capabilities={}))
    await db.commit()
    sessions = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    await DistributedWorker(sessions, worker.id)._verify_connectors()
    async with sessions() as fresh:
        registration = (await fresh.execute(select(DistributedWorkerRegistration).where(
            DistributedWorkerRegistration.worker_id == worker.id))).scalar_one()
        return registration.capabilities["connectors_verified"]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_the_worker_counts_a_connector_only_through_an_entry_it_may_use(db):
    project_id = await _project(db, {"jira_url": "https://jira.example.test"})
    assert await _verified(db, project_id) is False, "a Project.config URL verifies nothing (M-1)"

    await upsert_tool_config(db, tool_name="jira", project_id=project_id,
                             config={"jira_url": "https://jira.example.test"}, is_active=False)
    await db.commit()
    assert await _verified(db, project_id) is False, "an entry without access verifies nothing"

    entry = (await db.execute(select(BuiltInToolConfig).where(
        BuiltInToolConfig.project_id == project_id, BuiltInToolConfig.tool_name == "jira"))).scalar_one()
    entry.is_active = True
    await db.commit()
    assert await _verified(db, project_id) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("key, value", [
    ("jira_url", "https://jira.example.test"), ("jira_token", "plain"), ("kubeconfig_path", "/tmp/k"),
    ("confluence_auth_mode", "basic"),
])
async def test_the_admin_config_write_paths_refuse_connection_keys(client, auth_headers, db, key, value):
    project_id = await _project(db, {"k8s_context": "ws"})

    patched = await client.put(f"/api/v1/projects/{project_id}/config", json={key: value}, headers=auth_headers)
    updated = await client.patch(f"/api/v1/projects/{project_id}", json={"config": {key: value}}, headers=auth_headers)
    created = await client.post("/api/v1/projects", headers=auth_headers,
                                json={"name": f"refused-{uuid.uuid4().hex[:8]}", "config": {key: value}})

    for response in (patched, updated, created):
        assert response.status_code == 422, response.text
        [error] = response.json()["detail"]["errors"]
        assert error["code"] == "project_config_connection_key" and key in error["message"]
        assert value not in error["message"]
    assert await _config(db, project_id) == {"k8s_context": "ws"}


@pytest.mark.asyncio
async def test_clearing_a_connection_key_is_allowed(client, auth_headers, db):
    project_id = await _project(db, {"k8s_context": "ws"})

    cleared = await client.put(f"/api/v1/projects/{project_id}/config", headers=auth_headers, json={"jira_url": ""})

    assert cleared.status_code == 200, cleared.text
    assert not (await _config(db, project_id)).get("jira_url")


@pytest.mark.parametrize(("value", "carries"), [
    ("https://svc@jira.example.test", True), ("ssh://git@host/repo", True), ("svc@host", True),
    ("//svc:pw@host", True), ("https:\\\\svc:pw@host", True),
    ("https://jira.example.test", False), ("https://jira.example.test/a@b", False), ("https://h/p?x=a@b", False),
    ("https://h#a@b", False), ("jira.example.test:8443", False), ("/usr/bin/kubectl", False), (8443, False),
])
def test_userinfo_is_any_at_sign_in_the_authority_under_any_scheme(value, carries):
    assert carries_userinfo(value) is carries
