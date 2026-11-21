"""Observability O4: Health roll-up with honest states (unknown and disabled are never ok)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models import (
    BackgroundWorkerRunState,
    CircuitBreakerState,
    ConnectorHealth,
    ConnectorHealthLog,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
    TurnTrace,
)
from app.services.observability.health_read_model import health_overview
from app.services.observability.run_summary import run_summary_fields
from app.time_utils import utc_now
from tests.observability_support import add_trace, admin_user, call_as, session_for, user_with_role, workspace


def _rows(payload, group):
    return {item["component"]: item for item in next(g for g in payload["groups"] if g["key"] == group)["rows"]}


@pytest.mark.asyncio
async def test_health_rolls_up_with_honest_states(db):
    now = utc_now()
    name = f"servicenow-{uuid.uuid4().hex[:6]}"
    stale = f"jira-{uuid.uuid4().hex[:6]}"
    db.add(ConnectorHealth(connector_name=name, project_id="", status="error", error="invalid_client",
                           last_checked=now - timedelta(minutes=1)))
    db.add(ConnectorHealthLog(connector_name=name, project_id="", status="ok", checked_at=now - timedelta(hours=2)))
    for minutes in (40, 20, 1):
        db.add(ConnectorHealthLog(connector_name=name, project_id="", status="error",
                                  checked_at=now - timedelta(minutes=minutes)))
    db.add(ConnectorHealth(connector_name=stale, project_id="", status="ok", last_checked=now - timedelta(days=2)))
    db.add(BackgroundWorkerRunState(worker_name=f"projection-{uuid.uuid4().hex[:6]}", owner="knowledge", status="ok",
                                    started_at=now - timedelta(days=3), updated_at=now - timedelta(days=3)))
    db.add(CircuitBreakerState(connector_name=f"cb-{uuid.uuid4().hex[:6]}", state="open"))
    project = await workspace(db)
    connector = KnowledgeSourceConnector(project_id=project.id, connector_key="confluence", kind="confluence")
    db.add(connector)
    await db.flush()
    db.add(KnowledgeSourceSyncRun(connector_id=connector.id, project_id=project.id, state="failed",
                                  reason="auth_failed", started_at=now - timedelta(minutes=5)))
    admin = await admin_user(db)
    session = await session_for(db, admin)
    for outcome in ("failed", "failed", "completed", "failed"):
        add_trace(db, TurnTrace(session_id=session.id, provider="bedrock", model="model-x", raw_output={}),
                  run_summary_fields(run_key=f"req:{uuid.uuid4().hex}", raw_output={"error": "x"}
                                     if outcome == "failed" else {}, started_at=now - timedelta(seconds=3)))
    await db.commit()

    payload = await health_overview(db, checks={"scheduler": {"status": "disabled", "error": "disabled"},
                                                "retention_worker": {"status": "unknown", "error": "not started"}})

    connections = _rows(payload, "connections")
    failing = connections[f"{name} · global"]
    assert failing["status"] == "failing" and "3 failed checks" in failing["detail"]
    assert failing["since"] is not None
    assert connections[f"{stale} · global"]["status"] == "unknown", "a stale ok is not ok"
    platform = _rows(payload, "platform")
    assert platform["Scheduler"]["status"] == "disabled"
    assert platform["Retention worker"]["status"] == "unknown"
    assert any(item["status"] == "unknown" and item["component"].startswith("Worker projection-")
               for item in platform.values())
    assert next(iter(_rows(payload, "syncs").values()))["status"] == "failing"
    assert _rows(payload, "providers")["bedrock · model-x"]["status"] == "failing"
    assert _rows(payload, "background")["Circuit breakers"]["status"] == "degraded"
    assert payload["summary"]["failing"] >= 3 and payload["summary"]["unknown"] >= 2


@pytest.mark.asyncio
async def test_a_worker_idle_without_a_knowledge_store_is_neutral_and_a_real_runtime_failure_stays_red(db):
    """Not set up is a choice, never a fault: a fresh stack (projection worker not_configured, build runner
    runtime_unavailable) must not show "2 failing" when nothing is broken."""
    now = utc_now()
    idle, broken = f"projection-{uuid.uuid4().hex[:6]}", f"builder-{uuid.uuid4().hex[:6]}"
    db.add(BackgroundWorkerRunState(worker_name=idle, owner="knowledge", status="failed", error="not_configured",
                                    started_at=now, updated_at=now))
    db.add(BackgroundWorkerRunState(worker_name=broken, owner="knowledge", status="failed",
                                    error="runtime_unavailable", started_at=now, updated_at=now))
    await db.commit()

    platform = _rows(await health_overview(db, checks={}), "platform")
    assert platform[f"Worker {idle}"]["status"] == "disabled"
    assert platform[f"Worker {idle}"]["detail"].startswith("not configured")
    assert platform[f"Worker {broken}"]["status"] == "failing", "a configured runtime that fails stays red"


@pytest.mark.asyncio
async def test_health_route_is_admin_only_and_the_anonymous_probe_shows_status_only(client, db):
    admin = await admin_user(db)
    viewer = await user_with_role(db, "viewer")
    assert (await call_as(client, "GET", "/api/v1/observability/health", viewer)).status_code == 403
    response = await call_as(client, "GET", "/api/v1/observability/health", admin)
    assert response.status_code == 200
    assert [group["key"] for group in response.json()["groups"]] == [
        "platform", "connections", "syncs", "providers", "background"]
    # The probe (services/observability/endpoint_access.py): status only without a login.
    client.cookies.clear()
    probe = await client.get("/api/v1/health")
    assert probe.status_code == 200 and set(probe.json()) == {"status"}
