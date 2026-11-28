"""API tests for orchestrator routes."""


import pytest


@pytest.mark.asyncio
async def test_get_orchestrator_run_not_found(client, auth_headers):
    resp = await client.get("/api/v1/orchestrator/nonexistent-id", headers=auth_headers)
    assert resp.status_code == 404














