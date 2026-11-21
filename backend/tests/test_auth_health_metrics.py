"""Health, Prometheus metrics and runtime endpoints, including what anonymous callers can see."""

import pytest


@pytest.mark.asyncio
async def test_health(client, auth_headers):
    # An unauthenticated probe gets the overall status only; checks and configuration need a signed-in caller.
    client.cookies.clear()
    anonymous = await client.get("/api/v1/health")
    assert anonymous.status_code == 200 and set(anonymous.json()) == {"status"}
    resp = await client.get("/api/v1/health", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in {"ok", "degraded", "error"}
    assert data["summary"]["status"] == data["status"]
    assert "checks" in data
    assert "database" in data["checks"]
    assert "prefetch_worker" in data["checks"]
    assert data["configuration"]["security_defaults"]["status"] in {"secure", "local_only_defaults"}
    assert "local_only_default_fields" in data["configuration"]["security_defaults"]


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_lines(client, auth_headers):
    await client.get("/api/v1/health", headers=auth_headers)
    client.cookies.clear()
    assert (await client.get("/metrics")).status_code == 401
    resp = await client.get("/metrics", headers=auth_headers)
    assert resp.status_code == 200
    assert "octryx_api_requests_total" in resp.text
    assert "octryx_platform_health_status" in resp.text
    assert "octryx_workflow_run_state" in resp.text
    assert "prefetch_queue_depth" in resp.text


@pytest.mark.asyncio
async def test_a_scrape_runs_no_database_statement(client, db, monkeypatch):
    """Metrics never go through the database. Prometheus authenticates with the scrape token (no user
    lookup either), and rendering /metrics reads everything from memory."""
    from sqlalchemy import event

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "metrics_scrape_token", "scrape-secret-for-tests")
    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        response = await client.get("/metrics", headers={"Authorization": "Bearer scrape-secret-for-tests"})
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert response.status_code == 200 and "octryx_api_requests_total" in response.text
    assert statements == []


@pytest.mark.asyncio
async def test_runtime_endpoints_reveal_nothing_to_anonymous_callers(client, monkeypatch):
    from app.config import get_settings

    health = await client.get("/api/v1/health")
    assert health.status_code == 200 and set(health.json()) == {"status"}, "probes keep the status, nothing more"
    assert (await client.get("/health")).status_code == 404, "the probe path is /api/v1/health only"
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401
    monkeypatch.setattr(get_settings(), "metrics_scrape_token", "scrape-token-for-tests-only")
    assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401
    scraped = await client.get("/metrics", headers={"Authorization": "Bearer scrape-token-for-tests-only"})
    assert scraped.status_code == 200 and "octryx_api_requests_total" in scraped.text
