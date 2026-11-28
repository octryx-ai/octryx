"""Governed Workspace Knowledge enablement: closed states, audit, author-only."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.projection import workspace_provisioning as enablement
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace


async def _author(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="owner")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    return authorized, user_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client_present", "state", "outcome"),
    [(True, "ready", "postgres_index"), (False, "needs_configuration", "postgres_index_unavailable")],
)
async def test_every_outcome_is_a_closed_state_with_one_audit_row(db, monkeypatch, client_present, state, outcome):
    monkeypatch.setattr(enablement, "application_index_client", lambda: object() if client_present else None)
    authorized, user_id = await _author(db)

    result = await enablement.enable_workspace_knowledge(db, authorized=authorized, actor_id=user_id)

    assert (result.state, result.outcome) == (state, outcome)
    rows = (
        await db.execute(select(AuditLog).where(AuditLog.resource_id == authorized.project_id))
    ).scalars().all()
    enabled = [(row.action, row.details["state"]) for row in rows if row.action == "knowledge.workspace.enable"]
    assert enabled == [("knowledge.workspace.enable", state)]


@pytest.mark.asyncio
async def test_a_reader_cannot_enable_knowledge(client, db) -> None:
    workspace_id = await seed_workspace(db)
    reader_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()
    reader = await fetch_user(db, reader_id)
    from app.services.auth import create_access_token

    token = create_access_token(reader.id)
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/knowledge/enable", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
