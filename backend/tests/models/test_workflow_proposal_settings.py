"""The proposal timeout is an admin setting, not a constant."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog
from tests.workflow_proposal_support import (  # noqa: F401
    _answer,
    _project,
    _resolve,
    proposal_model,
)

pytestmark = pytest.mark.workflow_proposals

PATH = "/admin/chat/api/panel/policy-lists/workflow_proposal_settings"
SEED = {"timeout_seconds": 10}
PHASED_WORKFLOW = "incident-analysis"


async def _save(client, values) -> tuple[int, dict]:
    response = await client.put(PATH, json={"values": values})
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_the_seed_is_the_previous_behaviour_and_edits_are_refused_with_closed_codes(admin_client, db):
    lists = (await admin_client.get("/admin/chat/api/panel/policy-lists")).json()["lists"]
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
        status, body = await _save(admin_client, values)
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

    status, saved = await _save(admin_client, {"timeout_seconds": 20})
    assert status == 200, saved
    assert (saved["key"], saved["origin"], saved["matches_seed"]) == ("workflow_proposal_settings.v2", "admin", False)
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.resource_id == "workflow_proposal_settings"))
    ).scalars().all()
    assert [row.action for row in audit] == ["policy_list.updated"]
    reset = (await admin_client.post(f"{PATH}/reset")).json()
    assert (reset["values"], reset["key"]) == (SEED, "workflow_proposal_settings.v3")


