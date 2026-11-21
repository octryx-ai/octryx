"""A new Workspace may use every model cleared for its level."""

from __future__ import annotations

import pytest

from app.services.workspace_models.store import read_models

pytestmark = pytest.mark.asyncio


async def test_a_new_workspace_starts_with_all_cleared_models(client, auth_headers, db):
    response = await client.post("/api/v1/projects", headers=auth_headers,
                                 json={"name": "packmate-defaults-test", "description": "defaults"})
    assert response.status_code in (200, 201), response.text
    models = await read_models(db, response.json()["id"])
    assert models["contract"]["mode"] == "all_cleared", models["contract"]
