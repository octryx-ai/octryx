"""Global › Models: one read over providers, models and what the workspaces made of them — allowed in how many,
switched off where, default where — so the global level shows every narrowing."""

from __future__ import annotations

import uuid

import pytest

from app.models import Project
from app.services.workspace_models.overview import provider_state
from tests.policy_engine_support import bearer, make_user
from tests.services.workspace.test_workspace_models import _setup

ROUTE = "/api/v1/admin/model-catalog/overview"
MODELS = "/api/v1/admin/workspaces/{}/models"
SEAT: dict = {}  # every seat key is the seat route's: the models contract sends none


@pytest.mark.asyncio
async def test_the_overview_counts_where_each_model_is_allowed_off_or_default(client, db):
    admin = await make_user(db, admin=True)
    narrow, _ = await _setup(db, "internal")
    wide = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True,
                   config={"data_policy": {"classification": "internal"}})
    db.add(wide)
    await db.commit()
    body = {"mode": "selected", "selected": ["octryx-general", "octryx-secure"], "default": "octryx-general", "task_overrides": {},
            "seat": SEAT}
    saved = await client.put(MODELS.format(wide.id), json=body, headers=bearer(admin))
    assert saved.status_code == 200, saved.text
    only_general = {**body, "selected": ["octryx-general"]}
    assert (await client.put(MODELS.format(narrow.id), json=only_general, headers=bearer(admin))).status_code == 200

    view = (await client.get(ROUTE, headers=bearer(admin))).json()
    rows = {row["key"]: row for row in view["models"]}
    assert rows["octryx-general"]["label"] == "General model"
    assert rows["octryx-general"]["available_in"] >= 2
    assert {wide.name, narrow.name} <= set(rows["octryx-general"]["default_in"])
    assert narrow.name in rows["octryx-secure"]["off_in"] and wide.name not in rows["octryx-secure"]["off_in"]
    assert view["workspaces"] >= 2
    assert rows["octryx-general"]["provider_off"] is False
    gateway = next(row for row in view["providers"] if row["name"] == "Company gateway")
    assert gateway["state"] in {"connected", "failing"} and gateway["models_found"] >= 0
    assert not any("secret" in key or "api_key" in key for row in view["providers"] for key in row)


@pytest.mark.asyncio
async def test_only_platform_admins_read_the_overview(client, db):
    member = await make_user(db, admin=False)
    assert (await client.get(ROUTE, headers=bearer(member))).status_code == 403


def test_provider_state_reads_switch_and_health():
    class Row:
        def __init__(self, active, health):
            self.is_active, self.health_status = active, health
    assert provider_state(Row(False, "ok")) == "off"
    assert provider_state(Row(True, "error")) == "failing"
    assert provider_state(Row(True, None)) == "connected"
