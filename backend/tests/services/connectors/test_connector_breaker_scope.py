"""Health checks and circuit breakers are scoped per connection."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

import app.tools.registry as registry_module
from app.models import BuiltInToolConfig, CircuitBreakerState, ConnectorHealth, ConnectorHealthLog, Project
from app.services import circuit_breaker as circuit_breaker_package
from app.services.connector_health import prune_connector_health_log, refresh_connector_health
from app.services.connector_test_service import run_connector_connection_test
from app.time_utils import utc_now
from app.tools.context import ToolContext
from tests.factories import make_project


async def _workspace(db) -> Project:
    return await make_project(db, name=f"breaker-{uuid.uuid4().hex[:6]}", commit=True)


def _context(db, project_id: str) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=[project_id],
        roles=["admin"],
        session_id="session-1",
        project_config={"connectors": {"jira": {"enabled": True}}},
        db=db,
    )


@pytest.mark.asyncio
async def test_not_implemented_test_is_no_test_and_never_feeds_a_breaker(db):
    result = await run_connector_connection_test("connector-without-a-test", {})
    assert result["no_test"] is True

    async def no_test(_tool_name, _config):
        return result

    for _ in range(circuit_breaker_package.CIRCUIT_BREAKER_FAILURE_THRESHOLD + 1):
        health = await refresh_connector_health(db, connector_name="jira", config={}, run_connection_test=no_test)
    await db.commit()

    assert health["status"] == "no_test"
    assert health["error"] == ""
    assert await db.get(CircuitBreakerState, "jira@platform") is None


@pytest.mark.asyncio
async def test_failing_platform_check_does_not_block_a_workspace_with_its_own_connection(db, monkeypatch):
    own = await _workspace(db)
    inheriting = await _workspace(db)
    db.add(
        BuiltInToolConfig(
            id=str(uuid.uuid4()),
            tool_name="jira",
            project_id=own.id,
            config={"jira_url": "https://jira.own.example.test"},
            is_active=True,
        )
    )
    await db.commit()

    async def failing(_tool_name, _config):
        return {"ok": False, "summary": "auth failed"}

    for _ in range(circuit_breaker_package.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
        await refresh_connector_health(db, connector_name="jira", config={}, run_connection_test=failing)
    await db.commit()
    assert (await db.get(CircuitBreakerState, "jira@platform")).state == "open"

    async def dispatched(_tool_name, _params, _context):
        return {"issues": []}

    monkeypatch.setattr(registry_module, "_dispatch_registered_tool", dispatched)

    own_result = await registry_module.execute_tool_with_plugins("search_jira_tickets", {}, _context(db, own.id))
    blocked = await registry_module.execute_tool_with_plugins(
        "search_jira_tickets", {}, _context(db, inheriting.id)
    )

    assert own_result.get("circuit_breaker_state") is None
    assert "error" not in own_result
    assert blocked["circuit_breaker_state"] == "open"
    assert blocked["connector_name"] == "jira@platform"


@pytest.mark.asyncio
async def test_workspace_check_never_opens_the_platform_breaker(db):
    project = await _workspace(db)

    async def failing(_tool_name, _config):
        return {"ok": False, "summary": "auth failed"}

    for _ in range(circuit_breaker_package.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
        await refresh_connector_health(
            db, connector_name="jira", project_id=project.id, config={}, run_connection_test=failing
        )
    await db.commit()

    assert await db.get(CircuitBreakerState, "jira@platform") is None
    row = (
        await db.execute(
            select(ConnectorHealth).where(ConnectorHealth.connector_name == "jira", ConnectorHealth.project_id == project.id)
        )
    ).scalar_one()
    assert row.status == "error"


@pytest.mark.asyncio
async def test_health_log_keeps_seven_days(db):
    now = utc_now()
    db.add_all(
        [
            ConnectorHealthLog(connector_name="retention-probe", project_id="", status="ok", checked_at=now - timedelta(days=8)),
            ConnectorHealthLog(connector_name="retention-probe", project_id="", status="ok", checked_at=now - timedelta(days=1)),
        ]
    )
    await db.commit()

    removed = await prune_connector_health_log(db)
    await db.commit()

    kept = (
        await db.execute(select(ConnectorHealthLog).where(ConnectorHealthLog.connector_name == "retention-probe"))
    ).scalars().all()
    assert removed >= 1
    assert len(kept) == 1
