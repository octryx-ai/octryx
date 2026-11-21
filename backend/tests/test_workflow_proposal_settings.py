"""The proposal timeout is an admin setting, not a constant.

``workflow_proposal_settings`` is a governed record (versioned, audited) whose seed is the W27
behaviour: 10 s. Edits are refused with closed codes; the live value decides the proposal at the next turn.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.models import AuditLog
from tests.conftest import ADMIN_PASSWORD
from tests.workflow_proposal_support import (  # noqa: F401
    _answer,
    _project,
    _resolve,
    proposal_model,
)

pytestmark = pytest.mark.workflow_proposals

PATH = "/admin/chat/api/panel/policy-lists/workflow_proposal_settings"
SEED = {"timeout_seconds": 10}
# A seeded published phased workflow: the only kind a proposal can name.
PHASED_WORKFLOW = "incident-analysis"


async def _login(client) -> None:
    assert (await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})).status_code == 303


async def _save(client, values) -> tuple[int, dict]:
    response = await client.put(PATH, json={"values": values})
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_the_seed_is_the_previous_behaviour_and_edits_are_refused_with_closed_codes(client, db):
    await _login(client)
    lists = (await client.get("/admin/chat/api/panel/policy-lists")).json()["lists"]
    settings = next(entry for entry in lists if entry["list_id"] == "workflow_proposal_settings")
    assert settings["values"] == SEED and settings["origin"] == "seed" and settings["matches_seed"] is True
    assert settings["key"] == "workflow_proposal_settings.v1"

    refusals = {
        "missing field": {},
        "unknown field": {**SEED, "read_only_auto_apply_default": "high_confidence"},
        "not an object": ["timeout_seconds"],
        "timeout type": {**SEED, "timeout_seconds": "10"},
        "timeout bool": {**SEED, "timeout_seconds": True},
        "timeout zero": {**SEED, "timeout_seconds": 0},
        "timeout too long": {**SEED, "timeout_seconds": 61},
    }
    codes = {}
    for case, values in refusals.items():
        status, body = await _save(client, values)
        assert status == 422, (case, body)
        codes[case] = body["detail"]["code"]
    assert codes == {
        "missing field": "invalid_payload",
        "unknown field": "invalid_payload",
        "not an object": "invalid_payload",
        "timeout type": "invalid_entry",
        "timeout bool": "invalid_entry",
        "timeout zero": "out_of_range",
        "timeout too long": "out_of_range",
    }

    status, saved = await _save(client, {"timeout_seconds": 20})
    assert status == 200, saved
    assert (saved["key"], saved["origin"], saved["matches_seed"]) == ("workflow_proposal_settings.v2", "admin", False)
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.resource_id == "workflow_proposal_settings"))
    ).scalars().all()
    assert [row.action for row in audit] == ["policy_list.updated"]
    reset = (await client.post(f"{PATH}/reset")).json()
    assert (reset["values"], reset["key"]) == (SEED, "workflow_proposal_settings.v3")


@pytest.mark.asyncio
async def test_the_live_settings_decide_the_timeout(client, db, proposal_model):  # noqa: F811
    await _login(client)
    provider = proposal_model(_answer(PHASED_WORKFLOW))
    default = await _project(db)
    held = (await _resolve(db, project_id=default.id))["workflow_proposal"]
    assert (held["status"], held["reason_code"]) == ("needs_confirmation", "workflow_run_required")

    assert (await _save(client, {"timeout_seconds": 1}))[0] == 200
    original_chat = provider.chat

    async def slow_chat(**kwargs):
        await asyncio.sleep(1.5)
        return await original_chat(**kwargs)

    provider.chat = slow_chat
    timed_out = (await _resolve(db, project_id=default.id))["workflow_proposal"]
    assert (timed_out["status"], timed_out["reason_code"]) == ("none", "timeout")
