"""A webhook's raw secret is returned exactly once, on create and on rotate; reads stay masked."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Project
from app.models.integration.webhook import Webhook
from app.services.webhook_secret import resolve_webhook_secret


@pytest.mark.asyncio
async def test_create_and_rotate_return_the_working_secret_once_and_lists_stay_masked(client, auth_headers, db):
    project = (await db.execute(select(Project))).scalars().first()
    created = await client.post("/api/v1/webhooks", headers=auth_headers, json={
        "project_id": project.id, "name": "GitLab pull requests", "source_type": "scm_pull_request",
        "accept_untimestamped": True})
    assert created.status_code == 201, created.text
    hook_id, first = created.json()["id"], created.json()["secret"]
    webhook = await db.get(Webhook, hook_id)
    assert "*" not in first and first == await resolve_webhook_secret(db, webhook, purpose="test.read")

    listed = await client.get("/api/v1/webhooks", headers=auth_headers)
    assert [row["secret"] for row in listed.json() if row["id"] == hook_id] == ["***"]
    assert first not in listed.text

    rotated = await client.post(f"/api/v1/webhooks/{hook_id}/rotate-secret", headers=auth_headers)
    assert rotated.status_code == 200, rotated.text
    second = rotated.json()["secret"]
    db.expire_all()
    stored = await resolve_webhook_secret(db, await db.get(Webhook, hook_id), purpose="test.read")
    assert second != first and stored == second

    audits = (await db.execute(select(AuditLog).where(AuditLog.action == "webhook.secret_rotated",
                                                      AuditLog.resource_id == hook_id))).scalars().all()
    assert len(audits) == 1 and audits[0].user_id is not None
    assert second not in str(audits[0].details) and first not in str(audits[0].details)


@pytest.mark.asyncio
async def test_rotating_an_unknown_webhook_is_not_found(client, auth_headers):
    response = await client.post("/api/v1/webhooks/no-such-hook/rotate-secret", headers=auth_headers)
    assert response.status_code == 404
