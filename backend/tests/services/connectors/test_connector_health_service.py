import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import BuiltInToolConfig, CircuitBreakerState, ConnectorHealth, ConnectorHealthLog
from app.services import circuit_breaker as circuit_breaker_package
from app.services import connector_health as connector_health_package
from app.services import connector_health as connector_health_service_module
from app.services.connector_health import ConnectorHealthWorker, refresh_connector_health


def test_connector_health_service_shim_matches_package_exports():
    assert connector_health_service_module.refresh_connector_health is connector_health_package.refresh_connector_health
    assert connector_health_service_module.ConnectorHealthWorker is connector_health_package.ConnectorHealthWorker
    assert (
        connector_health_service_module.CONNECTOR_HEALTH_INTERVAL_SECONDS
        == connector_health_package.CONNECTOR_HEALTH_INTERVAL_SECONDS
    )


@pytest.mark.asyncio
async def test_refresh_connector_health_persists_current_row_log_and_circuit_breaker(db):
    async def ok_test(_tool_name: str, _config: dict):
        return {"ok": True, "summary": "reachable", "details": "all good"}

    health = await refresh_connector_health(
        db,
        connector_name="jira",
        config={"jira_url": "https://jira.example.com"},
        run_connection_test=ok_test,
    )
    await db.commit()

    assert health["status"] == "ok"
    stored = (
        await db.execute(
            select(ConnectorHealth).where(
                ConnectorHealth.connector_name == "jira",
                ConnectorHealth.project_id == "",
            )
        )
    ).scalar_one()
    assert stored.details == "all good"

    logs = (
        (await db.execute(select(ConnectorHealthLog).where(ConnectorHealthLog.connector_name == "jira")))
        .scalars()
        .all()
    )
    assert len(logs) == 1
    breaker = await db.get(CircuitBreakerState, "jira@platform")
    assert breaker is None or breaker.state == "closed"


@pytest.mark.asyncio
async def test_connector_health_worker_records_failures_and_opens_breaker(db):
    db.add(
        BuiltInToolConfig(
            id=str(uuid.uuid4()),
            tool_name="jira",
            project_id=None,
            config={"jira_url": "https://jira.example.com"},
            is_active=True,
        )
    )
    await db.commit()

    async def failing_test(_tool_name: str, _config: dict):
        return {"ok": False, "summary": "auth failed", "details": "401 unauthorized"}

    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    worker = ConnectorHealthWorker(session_factory, run_connection_test=failing_test, interval_seconds=60)
    for _ in range(circuit_breaker_package.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
        await worker.run_once(force=True)

    stored = (
        await db.execute(
            select(ConnectorHealth).where(
                ConnectorHealth.connector_name == "jira",
                ConnectorHealth.project_id == "",
            )
        )
    ).scalar_one()
    assert stored.status == "error"
    assert stored.error == "auth failed"

    logs = (
        (
            await db.execute(
                select(ConnectorHealthLog)
                .where(ConnectorHealthLog.connector_name == "jira")
                .order_by(ConnectorHealthLog.checked_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == circuit_breaker_package.CIRCUIT_BREAKER_FAILURE_THRESHOLD

    breaker = await db.get(CircuitBreakerState, "jira@platform")
    assert breaker is not None
    assert breaker.state == "open"
    assert breaker.failure_count >= 3
