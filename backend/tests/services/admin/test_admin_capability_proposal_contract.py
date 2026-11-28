"""Admin U1 contract: the Workspace proposal switch write."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog


@pytest.mark.asyncio
async def test_panel_proposal_switch_write_is_validated_audited_and_resettable(client, auth_headers, db):
    created = await client.post("/api/v1/projects", headers=auth_headers, json={"name": "u1-proposal-switch"})
    assert created.status_code in {200, 201}, created.text
    url = f"/admin/chat/api/panel/projects/{created.json()['id']}/config"

    refused = await client.put(url, headers=auth_headers, json={"workflow_proposal_policy": {"enabled": "off"}})
    disabled = await client.put(url, headers=auth_headers, json={"workflow_proposal_policy": {"enabled": False}})
    reloaded = await client.get(url, headers=auth_headers)
    reset = await client.put(url, headers=auth_headers, json={"workflow_proposal_policy": {"enabled": None}})

    assert refused.status_code == 400, refused.text
    assert "workflow_proposal_policy.enabled must be a boolean" in refused.json()["detail"]
    assert reloaded.json()["config"]["workflow_proposal_policy"] == {"enabled": False}
    assert disabled.status_code == 200 and reset.status_code == 200
    assert reset.json()["config"]["workflow_proposal_policy"] == {}
    audits = (
        (await db.execute(select(AuditLog).where(AuditLog.action == "admin.project_config.updated"))).scalars().all()
    )
    assert any((row.details or {}).get("project_id") == created.json()["id"] for row in audits), (
        "every accepted write is audited"
    )
