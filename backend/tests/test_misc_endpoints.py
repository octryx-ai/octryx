"""Tests for tasks and knowledge endpoints."""

import asyncio

import pytest

from tests.scripted_pool_support import scripted_turns  # noqa: F401 - fixture


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
async def test_scheduler_reload_limiter_grants_single_slot_under_concurrency(monkeypatch):
    from datetime import datetime, timedelta

    import app.api.routes.workflows.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "_scheduler_reload_last_call", None)

    results = await asyncio.gather(*[tasks_module._acquire_scheduler_reload_slot() for _ in range(25)])
    assert sum(results) == 1

    assert await tasks_module._acquire_scheduler_reload_slot() is False

    after_cooldown = datetime.utcnow() + tasks_module._scheduler_reload_cooldown + timedelta(seconds=1)
    assert await tasks_module._acquire_scheduler_reload_slot(now=after_cooldown) is True
