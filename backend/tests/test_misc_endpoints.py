"""Tests for tasks and knowledge endpoints."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Project, Session, Task, User


@pytest.mark.asyncio
async def test_list_tasks_empty(client, auth_headers):
    resp = await client.get("/api/v1/tasks", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_approvals_empty(client, auth_headers):
    resp = await client.get("/api/v1/approvals", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_audit(client, auth_headers):
    # auth_headers is the seeded admin; non-admins are refused (test_observability_admin_reads).
    resp = await client.get("/api/v1/audit", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_list_providers(client, auth_headers):
    resp = await client.get("/api/v1/providers", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_projects(client, auth_headers):
    resp = await client.get("/api/v1/projects", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(project["name"] == "acme-orders" for project in data)


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_trigger_task(client, auth_headers, db, monkeypatch):
    import app.agent.engine as engine
    from app.api.routes import tasks as tasks_route

    release = asyncio.Event()

    async def agent_turn(**_kwargs):
        # The trigger's contract is the run and its session, not the agent turn: the turn stays running until
        # the test releases it, then answers.
        await release.wait()
        yield SimpleNamespace(role="assistant", content="checked", tool_results=None)

    spawned: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def track(coroutine, **kwargs):
        spawned.append(real_create_task(coroutine, **kwargs))
        return spawned[-1]

    monkeypatch.setattr(engine, "run_agent", agent_turn)
    monkeypatch.setattr(tasks_route.asyncio, "create_task", track)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    rs_project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task_id = str(uuid.uuid4())

    task = Task(dispatch_binding="task_definition",
        id=task_id,
        project_id=rs_project.id,
        name="scheduled-check",
        description="Run a scheduled check",
        # Only agent_run is an agent turn; there is no other kind.
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={"prompt": "check acme-orders project"},
    )
    db.add(task)
    await db.commit()

    resp = await client.post(f"/api/v1/tasks/{task_id}/trigger", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert data["session_id"]
    assert data["task_run_id"]

    resp_second = await client.post(f"/api/v1/tasks/{task_id}/trigger", headers=auth_headers)
    assert resp_second.status_code == 200
    data_second = resp_second.json()
    assert data_second["status"] == "running"
    assert data_second["session_id"] == data["session_id"]

    reused_session = await db.get(Session, data["session_id"])
    assert reused_session is not None
    assert reused_session.metadata_["task_id"] == task_id
    assert reused_session.metadata_["trigger"] == "manual"
    # The background run finishes inside the test; nothing holds the database after it.
    release.set()
    await asyncio.wait_for(asyncio.gather(*spawned), timeout=30)


@pytest.mark.asyncio
async def test_scheduler_reload_limiter_grants_single_slot_under_concurrency(monkeypatch):
    """Concurrent callers racing the reload rate limiter get exactly one slot."""
    import asyncio
    from datetime import datetime, timedelta

    import app.api.routes.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "_scheduler_reload_last_call", None)

    results = await asyncio.gather(*[tasks_module._acquire_scheduler_reload_slot() for _ in range(25)])
    assert sum(results) == 1

    # Still within cooldown: no further slot is granted.
    assert await tasks_module._acquire_scheduler_reload_slot() is False

    # After the cooldown window elapses, a new slot is granted again.
    after_cooldown = datetime.utcnow() + tasks_module._scheduler_reload_cooldown + timedelta(seconds=1)
    assert await tasks_module._acquire_scheduler_reload_slot(now=after_cooldown) is True
