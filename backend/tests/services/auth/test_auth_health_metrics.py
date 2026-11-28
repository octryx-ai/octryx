"""Health, Prometheus metrics and runtime endpoints, including what anonymous callers can see."""

import pytest


@pytest.mark.asyncio
async def test_a_scrape_runs_no_database_statement(client, db, monkeypatch):
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
